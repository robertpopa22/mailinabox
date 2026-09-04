-- Candidate only: no automatic registration, transport or production integration.
local M = {}
M.security_symbols = {
  DBL_SPAM=true, DBL_ABUSE=true, URIBL_BLACK=true, RSPAMD_URIBL=true,
  SURBL_MULTI=true, FROM_NAME_SPOOFS_RCPT_DOMAIN=true, GPT_SPAM=true,
  CLAM_VIRUS=true, MIME_EXE=true, MIME_BAD_EXTENSION=true,
  MIME_ENCRYPTED_ARCHIVE=true, MIME_ENCRYPTED_PDF=true,
}
local function number(v)
  local n = tonumber(v)
  if n and n == n and n ~= math.huge and n ~= -math.huge then return n end
end
local function epoch(v)
  local n = number(v)
  if n and n >= 0 and n % 1 == 0 then return n end
end
local function domain(d)
  if type(d) ~= 'string' or #d > 253 or not d:find('%.') or
      d:find('[^a-z0-9.%-]') or d:find('%.%.') or d:sub(1,1)=='.' or d:sub(-1)=='.' then return nil end
  for label in d:gmatch('[^.]+') do
    if #label>63 or not label:match('^[a-z0-9]') or not label:match('[a-z0-9]$') then return nil end
  end
  return d
end
local function email(s)
  if type(s)~='string' or #s>254 then return nil end
  s=s:lower()
  local l,d=s:match('^([^@]+)@([^@]+)$')
  if not l or #l>64 or l:find('[^a-z0-9!#$%%&\'+/=?^_`{|}~.%-]') or
      l:sub(1,1)=='.' or l:sub(-1)=='.' or l:find('%.%.') or not domain(d) then return nil end
  return s,d
end
local function present(symbols,name) return symbols[name] ~= nil and symbols[name] ~= false end
function M.decision(c, lookup, now)
  local function blocked(reason) return {eligible=false, apply=false, reason=reason} end
  if type(c)~='table' or type(lookup)~='function' then return blocked('invalid_context') end
  local observed,expires=epoch(lookup('__observed')),epoch(lookup('__expires'))
  now=number(now)
  if tostring(lookup('__schema'))~='1' or not observed or not expires or not now or
      expires<=observed or expires-observed>3600 or observed>now or now>=expires then return blocked('stale') end
  if c.authenticated ~= false or c.local_outbound ~= false then return blocked('outbound_or_unknown') end
  if c.header_from_count~=1 or type(c.from)~='table' or #c.from~=1 then return blocked('ambiguous_from') end
  local sender,sd=email(c.from[1]); local smtp=email(c.smtp_from)
  if not sender or not smtp then return blocked('invalid_sender') end
  if tostring(lookup('domain:'..sd))=='1' then return blocked('local_sender') end
  local senderhex=sender:gsub('.',function(ch) return string.format('%02x',string.byte(ch)) end)
  if tostring(lookup('senderhex:'..senderhex))~='1' then return blocked('unknown_sender') end
  if type(c.recipients)~='table' or #c.recipients==0 then return blocked('missing_recipients') end
  for _,r in ipairs(c.recipients) do
    local address,rd=email(r)
    if not address or tostring(lookup('domain:'..rd))~='1' then return blocked('nonlocal_recipient') end
  end
  if c.bulk~=false or c.list~=false or c.bounce~=false or
      (c.auto_submitted~=nil and (type(c.auto_submitted)~='string' or c.auto_submitted:lower()~='no')) then return blocked('automated_or_unknown') end
  local symbols=c.symbols
  if type(symbols)~='table' or not present(symbols,'DMARC_POLICY_ALLOW') then return blocked('dmarc_unverified') end
  for name,value in pairs(symbols) do
    if value~=false then
      local upper=name:upper()
      if upper:match('^DMARC') and (upper:find('NA',1,true) or upper:find('REJECT',1,true) or upper:find('QUARANTINE',1,true) or upper:find('SOFTFAIL',1,true) or upper:find('DNSFAIL',1,true)) then return blocked('dmarc_conflict') end
      local configured=c.security_symbols or M.security_symbols
      if configured[name] or upper:find('PHISH',1,true) or upper:find('VIRUS',1,true) or upper:find('MALWARE',1,true) or upper:find('FUZZY_DENIED',1,true) or upper:find('BLACKLIST',1,true) then return blocked('security') end
    end
  end
  local total,threshold=number(c.total),number(c.reject_threshold)
  if c.pre_result~=false or not total or not threshold or total>=threshold then return blocked('pre_result_or_reject') end
  local bayes=number(symbols.BAYES_SPAM)
  if not bayes or bayes<=1 then return {eligible=true,apply=false,reason='eligible'} end
  return {eligible=true,apply=true,reason='cap_would_apply',original_bayes=bayes,cap=1.0,delta=bayes-1,proposed_total=total-(bayes-1)}
end

function M.context_from_task(task)
  local ok,context=pcall(function()
    local function addresses(items)
      assert(type(items)=='table')
      local result={}
      for _,item in ipairs(items) do
        assert(type(item)=='table' and type(item.addr)=='string')
        result[#result+1]=item.addr
      end
      return result
    end
    local from=addresses(task:get_from('mime'))
    local smtp=addresses(task:get_from('smtp'))
    local recipients=addresses(task:get_recipients('smtp'))
    local symbols={}
    local all=task:get_symbols_all()
    assert(type(all)=='table')
    for _,symbol in ipairs(all) do
      assert(type(symbol.name)=='string' and number(symbol.score))
      assert(symbols[symbol.name]==nil)
      symbols[symbol.name]=symbol.score
    end
    local function has(name)
      local value=task:has_symbol(name)
      assert(type(value)=='boolean')
      return value
    end
    local function header(name)
      local value=task:get_header(name)
      assert(value==nil or type(value)=='string')
      return value
    end
    local user=task:get_user()
    assert(user==nil or type(user)=='string')
    local precedence=header('Precedence')
    if precedence then precedence=precedence:lower():match('^%s*(.-)%s*$') end
    local count=task:get_header_count('From')
    assert(type(count)=='number')
    local score=task:get_metric_score()
    assert(type(score)=='table' and number(score[1]))
    local threshold=task:get_metric_threshold('reject')
    assert(number(threshold))
    local pre_result=task:has_pre_result()
    assert(type(pre_result)=='boolean')
    return {from=from,header_from_count=count,smtp_from=#smtp==1 and smtp[1] or nil,
      recipients=recipients,authenticated=user~=nil and user~='',local_outbound=has('LOCAL_OUTBOUND'),
      bulk=has('HAS_LIST_UNSUB') or has('PRECEDENCE_BULK') or has('BULK_MARKETING_MULTI_SIGNAL') or
        precedence=='bulk' or precedence=='list' or precedence=='junk',
      list=has('MAILLIST') or header('List-Id')~=nil or header('List-Unsubscribe')~=nil,
      bounce=has('BOUNCE') or #smtp~=1 or not email(smtp[1]),auto_submitted=header('Auto-Submitted'),
      symbols=symbols,total=score[1],reject_threshold=threshold,pre_result=pre_result}
  end)
  if not ok then error('active-client context adapter failed',0) end
  return context
end

function M.register(cfg,options)
  options=options or {}
  assert(options.mode==nil or options.mode=='shadow' or options.mode=='enforce','invalid active-client mode')
  -- Explicit adapter required: no guesses about task APIs or action thresholds.
  assert(type(options.context)=='function','validated task context adapter required')
  assert(type(options.lookup)=='function','atomic hash-map lookup required')
  local name='ACTIVE_CLIENT_BAYES_CANDIDATE'
  local id=cfg:register_symbol({name=name,type='postfilter',priority=20,score=0,flags='nostat',
    callback=function(task)
      local ok,result=pcall(function()
        local context=options.context(task)
        context.security_symbols=options.security_symbols or M.security_symbols
        return M.decision(context,options.lookup,(options.now or os.time)())
      end)
      if not ok then task:insert_result(name,0,'blocked_adapter_error'); return end
      if result.apply then
        if options.mode=='enforce' then task:adjust_result('BAYES_SPAM',result.cap) end
        task:insert_result(name,0,string.format('%s;bayes=%g;cap=%g',options.mode=='enforce' and 'cap_applied' or 'cap_would_apply',result.original_bayes,result.cap))
      elseif result.eligible or result.reason=='stale' then
        task:insert_result(name,0,result.eligible and 'eligible' or 'blocked_stale')
      end
    end})
  if type(cfg.register_dependency)=='function' then
    cfg:register_dependency('GREYLIST_SAVE',name)
    cfg:register_dependency('SPAM_REPORT_HEADER',name)
  end
  return id
end
function M.install(cfg,options)
  options=options or {}
  assert(options.mode==nil or options.mode=='shadow' or options.mode=='enforce','invalid active-client mode')
  assert(type(options.map_path)=='string' and options.map_path~='','active-client map_path required')
  local map=cfg:add_map({url=options.map_path,type='hash',description='Atomic expiring exact active-client senders'})
  assert(map,'active-client map registration failed')
  return M.register(cfg,{mode=options.mode,security_symbols=options.security_symbols,now=options.now,
    context=M.context_from_task,lookup=function(key) return map:get_key(key) end})
end
return M
