-- Bounded, brand-specific identity checks. No URL fetching or training.
local M = {}
local brands = {
  netflix = {'netflix.com'}, paypal = {'paypal.com'},
  microsoft = {'microsoft.com','microsoftonline.com','office.com','office365.com','microsoftadvertising.com'},
  apple = {'apple.com'}, icloud = {'apple.com','icloud.com'},
  google = {'google.com','accounts.google.com'},
  amazon = {'amazon.com','amazon.de','amazon.co.uk','amazon.fr','amazon.it','amazon.es'},
  spotify = {'spotify.com'}, dropbox = {'dropbox.com'},
  revolut = {'revolut.com'}, dhl = {'dhl.com','dhl.de'},
}
local confusable = {
  ['ă']='a',['â']='a',['Ă']='a',['Â']='a',['ș']='s',['ş']='s',
  ['ț']='t',['ţ']='t',['î']='i',['Ș']='s',['Ț']='t',['Î']='i',
  ['а']='a',['А']='a',['е']='e',['Е']='e',['о']='o',['О']='o',
  ['р']='p',['Р']='p',['с']='c',['С']='c',['х']='x',['Х']='x',
  ['і']='i',['І']='i',['ӏ']='l',['у']='y',['У']='y',
}
function M.normalize(text)
  text=tostring(text or ''):sub(1,24000)
  for ch, replacement in pairs(confusable) do text=text:gsub(ch,replacement) end
  return text:lower()
end
function M.skeleton(text)
  return M.normalize(text):gsub('[il1|]','i'):gsub('0','o'):gsub('[^a-z0-9 ]',' ')
end
local function contains(text, word)
  return (' '..text..' '):find('%f[%w]'..word..'%f[%W]') ~= nil
end
local function legitimate(domain, allowed)
  domain=M.normalize(domain):gsub('%.$','')
  for _,d in ipairs(allowed) do
    if domain==d or domain:sub(-#d-1)=='.'..d then return true end
  end
  return false
end
function M.evaluate(name, domain, subject, body, local_outbound)
  if local_outbound then return nil end
  local display, subj = M.skeleton(name), M.skeleton(subject)
  local text=M.normalize(body)
  -- Imperative/action plus sensitive target, never money/urgency alone.
  local request, strong_request=false,false
  local verbs={'actualizeaz','confirm','verific','introdu','furniz','reintrodu','update','verify','confirm','enter','provide','reset'}
  local targets={'facturare','plata','card','parol','credential','abonament','contul','account','billing','payment','password','subscription'}
  for _,v in ipairs(verbs) do
    local start=1
    while true do
      local a,b=text:find('%f[%a]'..v..'%a*',start)
      if not a then break end
      local near=text:sub(b+1,b+150)
      -- Quoted safety advice is deliberately not positive evidence.
      local prefix=text:sub(math.max(1,a-35),a-1)
      local negated=prefix:find('nu%s+[%a%s]*$') or prefix:find('never%s+[%a%s]*$') or prefix:find('do not%s+[%a%s]*$')
      if not negated then
        for _,t in ipairs(targets) do
          if near:find('%f[%a]'..t) then
            request=true
            if t=='card' or t=='parol' or t=='password' or t=='credential' or
               near:find('%f[%a]datele') or near:find('%f[%a]detali') or
               near:find('%f[%a]information') or near:find('%f[%a]details') then strong_request=true end
          end
        end
      end
      start=b+1
    end
  end
  for brand,allowed in pairs(brands) do
    local key=M.skeleton(brand)
    local in_display=contains(display,key)
    if not legitimate(domain,allowed) and (in_display or (contains(subj,key) and strong_request)) then
      if request then return 'BRAND_SENSITIVE_MISMATCH',brand end
      if in_display and not contains(tostring(name or ''):lower(),brand) then return 'BRAND_CONFUSABLE_MISMATCH',brand end
    end
  end
  return nil
end
function M.skip_ai(score, threshold)
  return type(score)=='number' and type(threshold)=='number' and threshold>0 and
    score>=math.max(8,threshold+3)
end
function M.install(config)
  local mime=require 'lua_mime'
  local parent=config:register_symbol({name='BRAND_IDENTITY_CHECK',score=0,flags='nostat',callback=function(task)
    local sender=(task:get_from('mime') or {})[1] or {}
    local body=mime.extract_text_limited(task,{max_bytes=16000,max_words=2500,min_words=0,strip_quotes=true,strip_reply_headers=true,smart_trim=true})
    local symbol,brand=M.evaluate(sender.name,sender.domain,task:get_subject(),body and body.text or '',task:get_user()~=nil or task:has_symbol('LOCAL_OUTBOUND'))
    if symbol then task:insert_result(symbol,1,brand) end
  end})
  for _,symbol in ipairs({'BRAND_SENSITIVE_MISMATCH','BRAND_CONFUSABLE_MISMATCH'}) do
    config:register_symbol({name=symbol,type='virtual',parent=parent,score=7.0,group='brand_identity_guard',description='Claimed brand and sender domain disagree; corroborated by sensitive request or visual impersonation'})
  end
  config:register_dependency('GPT_CHECK','BRAND_IDENTITY_CHECK')
  local gate=config:register_symbol({name='GPT_SELECTIVITY_CHECK',type='postfilter',priority=6,score=0,flags='nostat',callback=function(task)
    local result=task:get_metric_result()
    -- GPT_HAM can subtract at most 2 with current policy. At 8 points,
    -- even strongest ham remains spam (>5); preserve a further point of margin.
    -- Recalibrate this bound if GPT_HAM weights or other postfilters change.
    -- Normal filters/composites have completed; GPT runs at postfilter priority 5.
    if result and M.skip_ai(result.score,task:get_metric_threshold('add header')) then
      if task:disable_symbol('GPT_CHECK') then task:insert_result('GPT_SKIPPED_DECIDED',1) end
    end
  end})
  config:register_symbol({name='GPT_SKIPPED_DECIDED',type='virtual',parent=gate,score=0,group='gpt',description='AI skipped: deterministic score at least 8, above maximum GPT ham rescue range'})
  config:register_dependency('GPT_SELECTIVITY_CHECK','BRAND_IDENTITY_CHECK')
  config:register_dependency('GPT_CHECK','GPT_SELECTIVITY_CHECK')
  config:register_symbol({name='GPT_BACKEND_UNAVAILABLE',type='postfilter',priority=-10,score=0,flags='nostat',callback=function(task)
    if not task:has_symbol('GPT_UNCERTAIN') then return end
    local raw=task:get_mempool():get_variable('gpt_result')
    if raw then
      local parser=require('ucl').parser()
      if parser:parse_string(raw) then
        local result=parser:get_object()
        if result and not result.model then
          task:insert_result('GPT_BACKEND_UNAVAILABLE',1)
          require('rspamd_logger').warnx(task,'AI backend unavailable: no successful model result; deterministic filtering remains active')
        end
      end
    end
  end})
  config:register_dependency('GPT_BACKEND_UNAVAILABLE','GPT_CHECK')
  local account_check=config:register_symbol({name='GSA_ACCOUNT_CHECK',type='postfilter',priority=-20,score=0,flags='nostat',callback=function(task)
    if not task:has_symbol('GSA_ACCOUNT_PHISHING_CANDIDATE') or task:get_user()~=nil or task:has_symbol('LOCAL_OUTBOUND') then return end
    -- One contribution per phishing signal family, after deterministic AND AI checks.
    for _,symbol in ipairs({'BRAND_SENSITIVE_MISMATCH','BRAND_CONFUSABLE_MISMATCH','BRAND_IMPERSONATION','COURIER_IMPERSONATION','PHISHING','PHISHED_OPENPHISH','PHISHED_PHISHTANK','GPT_PHISHING','SPOOF_DISPLAY_NAME'}) do
      if task:has_symbol(symbol) then return end
    end
    task:insert_result('GSA_ACCOUNT_PHISHING',1)
  end})
  config:register_symbol({name='GSA_ACCOUNT_PHISHING',type='virtual',parent=account_check,score=2.0,group='brand_identity_guard',description='Multiple account-phishing phrase families from audited SpamAssassin subset; deduplicated'})
  config:register_dependency('GSA_ACCOUNT_CHECK','GPT_BACKEND_UNAVAILABLE')
end
return M
