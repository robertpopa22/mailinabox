local source=arg[0]:match('^(.*[/\\])') or ''
local m=dofile(source..'active_clients.lua')
local function senderkey(s) return 'senderhex:'..s:gsub('.',function(ch) return string.format('%02x',string.byte(ch)) end) end
local map={__schema='1',__observed='1000',__expires='1600',
 [senderkey('alice+tag@example.org')]='1',['domain:internal.example']='1'}
local function lookup(k) return map[k] end
local function context(total)
 return {from={'Alice+Tag@example.org'},header_from_count=1,smtp_from='bounce@example.org',
 recipients={'desk@internal.example'},authenticated=false,local_outbound=false,bulk=false,list=false,bounce=false,
 auto_submitted='no',symbols={DMARC_POLICY_ALLOW=0,BAYES_SPAM=6.5,MIME_BAD_ATTACHMENT=1.6},
 total=total or 9.27,reject_threshold=15,pre_result=false}
end
local function check(c,reason,now)
 local r=m.decision(c,lookup,now or 1200)
 assert(not r.apply and r.reason==reason,r.reason)
end
assert(math.abs(m.decision(context(5.27),lookup,1200).proposed_total - (-0.23))<0.000001)
assert(math.abs(m.decision(context(),lookup,1200).proposed_total-3.77)<0.000001)
check(context(),'stale',1600)
map[senderkey('alice+tag@example.org')]=nil;check(context(),'unknown_sender')
map[senderkey('alice+tag@example.org')]='1';assert(m.decision(context(),lookup,1200).apply)
local hashed=context();hashed.from={'alice+#tag@example.org'}
map[senderkey('alice+#tag@example.org')]='1';assert(m.decision(hashed,lookup,1200).apply)
-- Shared active relationships are already resolved by the map producer.
assert(m.decision(context(),lookup,1200).apply)
local c=context();c.from={'alice@example.org'};check(c,'unknown_sender')
c=context();c.symbols.DMARC_POLICY_ALLOW=nil;check(c,'dmarc_unverified')
c=context();c.header_from_count=2;check(c,'ambiguous_from')
c=context();c.from={'desk@internal.example'};check(c,'local_sender')
c=context();c.authenticated=true;check(c,'outbound_or_unknown')
c=context();c.local_outbound=true;check(c,'outbound_or_unknown')
c=context();c.recipients[2]='elsewhere@example.org';check(c,'nonlocal_recipient')
c=context();c.list=true;check(c,'automated_or_unknown')
c=context();c.symbols.CLAM_VIRUS=0;check(c,'security')
c=context();c.symbols.SOME_PHISHING_CHECK=0;check(c,'security')
c=context(15);check(c,'pre_result_or_reject')
c=context();c.pre_result=true;check(c,'pre_result_or_reject')
c=context();c.symbols.DMARC_POLICY_REJECT=0;check(c,'dmarc_conflict')
-- Shadow must not modify BAYES_SPAM, enforce only adjusts its absolute score.
local callback,dependencies,adjustments=nil,{},0
local cfg={register_symbol=function(_,spec) callback=spec.callback;return 1 end,
 register_dependency=function(_,target,dependency) dependencies[target]=dependency end}
local task={insert_result=function() end,adjust_result=function(_,symbol,score)
 assert(symbol=='BAYES_SPAM' and score==1);adjustments=adjustments+1 end}
m.register(cfg,{context=function() return context() end,lookup=lookup,now=function() return 1200 end})
callback(task);assert(adjustments==0)
m.register(cfg,{context=function() return context() end,lookup=lookup,now=function() return 1200 end,mode='enforce'})
callback(task);assert(adjustments==1)
assert(dependencies.GREYLIST_SAVE and dependencies.SPAM_REPORT_HEADER)
local mock={
 get_from=function(_,kind) return {{addr=kind=='mime' and 'Alice+Tag@example.org' or 'bounce@example.org'}} end,
 get_recipients=function() return {{addr='desk@internal.example'}} end,
 get_symbols_all=function() return {{name='DMARC_POLICY_ALLOW',score=0},{name='BAYES_SPAM',score=6.5}} end,
 has_symbol=function() return false end,get_header=function() return nil end,
 get_user=function() return nil end,get_header_count=function() return 1 end,
 get_metric_score=function() return {9.27,15} end,get_metric_threshold=function() return 15 end,
 has_pre_result=function() return false end,insert_result=function() end,
}
local actual=m.context_from_task(mock)
assert(actual.from[1]=='Alice+Tag@example.org' and actual.smtp_from=='bounce@example.org')
assert(actual.authenticated==false and actual.local_outbound==false and not actual.bulk and not actual.list)
assert(m.decision(actual,lookup,1200).apply)
cfg.add_map=function(_,spec)
 assert(spec.type=='hash' and spec.url=='/synthetic/active.map')
 return {get_key=function(_,key) return lookup(key) end}
end
m.install(cfg,{map_path='/synthetic/active.map',now=function() return 1200 end})
callback(mock) -- implicit shadow works with no adjust_result API on the task
local old_header=mock.get_header
mock.get_header=function(_,name) if name=='List-Id' then return '<synthetic.example>' end end
assert(m.context_from_task(mock).list)
mock.get_header=old_header
assert(not pcall(function() m.install(cfg,{mode='enfroce',map_path='/synthetic/map'}) end))
mock.get_metric_score=function() error('private raw details') end
local success,failure=pcall(function() m.context_from_task(mock) end)
assert(not success and not failure:find('private',1,true))
print('active_clients synthetic tests passed')
