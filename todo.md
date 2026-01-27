
- [ ] add the ability to deploy to a specific ec2 instance, such that you only have ssh access and nothing else to that instance (dev servers)

- [ ] Test the vercel deployment option.

- [ ] Add the ability to search all cloud accounts (eg cloudflare, gcp, azure, porkbun) for a domain, and then update the dns settings in that respective cloud account but use the primary cloud account the user specified for the https cert, cdn, load balancer, app server, etc


- [ ] with s3, is it possible to only upload files that changed? 

- [x] when you deploy to s3, revoke the entire cloudfront cdn cache for the relevant cdn
- [ ] i need a way to teardown all relevant infrastructure so it can be re-built on next deploy. this can be used to solve bugs, or times where infra that was already set up is bugged out