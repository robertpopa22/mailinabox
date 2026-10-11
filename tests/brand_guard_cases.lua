-- Execute with rspamadm lua; pure policy tests, no mailbox/network access.
local guard=dofile('setup/geseidl_edition/zones/spam/brand_guard.lua')
local cases={
 {'Netflix lookalike','NetfIix','unrelated.example','Contul tau Netflix este suspendat','Actualizeaza detaliile de facturare',false,'BRAND_SENSITIVE_MISMATCH'},
 {'Netflix exact','Netflix','evil.test','Cont suspendat','Actualizeaza datele de abonament',false,'BRAND_SENSITIVE_MISMATCH'},
 {'subject claim','Support','evil.test','Netflix account suspended','Update your billing information',false,'BRAND_SENSITIVE_MISMATCH'},
 {'PayPal','PayPaI','evil.test','Account suspended','Verify your payment information',false,'BRAND_SENSITIVE_MISMATCH'},
 {'cross brand','PayPal','netflix.com','Subscription','Update your payment information',false,'BRAND_SENSITIVE_MISMATCH'},
 {'Microsoft','Microsoft','evil.test','Access expired','Reset your account password',false,'BRAND_SENSITIVE_MISMATCH'},
 {'Google','Google','evil.test','Account','Verify your account now',false,'BRAND_SENSITIVE_MISMATCH'},
 {'courier','DHL','evil.test','Delivery','Confirm your payment information',false,'BRAND_SENSITIVE_MISMATCH'},
 {'evil suffix','Netflix','netflix.com.evil.test','Billing','Update your payment information',false,'BRAND_SENSITIVE_MISMATCH'},
 {'Cyrillic display','Nеtflix','evil.test','Billing','Update your subscription',false,'BRAND_SENSITIVE_MISMATCH'},
 {'Cyrillic no request','Nеtflix','evil.test','Hello','Your subscription expired',false,'BRAND_CONFUSABLE_MISMATCH'},
 {'confusable without request','NetfIix','evil.test','Hello','Your subscription expired',false,'BRAND_CONFUSABLE_MISMATCH'},
 {'legit Netflix','Netflix','netflix.com','Billing','Update your payment information',false,nil},
 {'legit subdomain','Netflix','mailer.netflix.com','Billing','Update your payment information',false,nil},
 {'legit Google','Google','accounts.google.com','Security','Verify your account',false,nil},
 {'legit Microsoft ads','Microsoft Advertising','microsoftadvertising.com','Webinar','Update your account',false,nil},
 {'ordinary invoice','Supplier','supplier.test','Invoice 123','Factura abonament. Plata in 30 de zile.',false,nil},
 {'ordinary receipt','Shop','shop.test','Payment confirmed','Your payment is confirmed. Thank you.',false,nil},
 {'mentions brand','Supplier','supplier.test','Invoice Microsoft licenses','Please pay attached invoice',false,nil},
 {'reseller invoice verification','Supplier','supplier.test','Factura Microsoft','Verificati factura si confirmati plata abonamentului',false,nil},
 {'tenant notification','Acme IT','acme.test','Microsoft account','Verify your account to continue',false,nil},
 {'security advice','Expert','expert.test','Netflix security','Never provide your password or payment details by email',false,nil},
 {'RO safety advice','Expert','expert.test','Netflix frauda','Nu introduceti datele de card in linkuri suspecte',false,nil},
 {'quoted irrelevant brand','Expert','expert.test','Technical report','Netflix was mentioned. Update your account',false,nil},
 {'authenticated outbound','Netflix','geseidl.ro','Billing','Update your payment information',true,nil},
}
for _,c in ipairs(cases) do
 local actual=guard.evaluate(c[2],c[3],c[4],c[5],c[6])
 assert(actual==c[7],c[1]..': expected '..tostring(c[7])..' got '..tostring(actual))
end
print('PASS '..#cases..' identity policy cases')
for _,c in ipairs({
 {4.99,5,false},{5,5,false},{9.48,5,true},
 {5.52,5,false},{20,5,true},{-1,5,false},
 {9.48,10,false},{9.48,0,false},{9.48,false,false},
 {7.99,5,false},{8,5,true},{8.01,5,true},
}) do assert(guard.skip_ai(c[1],c[2])==c[3],'AI selectivity boundary failed') end
print('PASS 12 AI selectivity boundary cases')
