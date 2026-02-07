
- [ ] add the ability to deploy to a specific ec2 instance, such that you only have ssh access and nothing else to that instance (dev servers)

- [ ] Test the vercel deployment option.

- [ ] Add the ability to search all cloud accounts (eg cloudflare, gcp, azure, porkbun) for a domain, and then update the dns settings in that respective cloud account but use the primary cloud account the user specified for the https cert, cdn, load balancer, app server, etc


- [x] with s3, is it possible to only upload files that changed? 

- [x] when you do any deployment (any type), invalidate the relevant CDN cache (AWS: CloudFront; S3 and Fargate both invalidate after deploy)
- [ ] 
- [x] i need a way to teardown all relevant infrastructure so it can be re-built on next deploy. this can be used to solve bugs, or times where infra that was already set up is bugged out. this can be triggered with a new --destroy flag, which will ask the user to confirm with the ui before everything is torn down. 


- [x] migrate to buildx Buildx is Docker’s CLI for the BuildKit builder and gives you explicit control over platform and cache. Your deploy uses --platform=linux/amd64 for Fargate, but Docker’s default cache doesn’t separate layers by architecture, so a build on ARM64 (e.g. your Mac) can cache ARM64 layers and then fail when the same cache is reused for an AMD64 build inside the container (or the other way around). With Buildx you can send cache to architecture-specific locations (e.g. --cache-to type=local,dest=./.buildx-cache-amd64 or a registry tag like buildcache:amd64), and use the matching --cache-from when building, so each platform (amd64 vs arm64) has its own cache and they never get mixed. That way you can run the same deploy command both on your host and inside the dev container without platform/cache conflicts, and still get fast, correct builds.


- [ ] when you do a faragte deploy, you need to ensure that the new tasks you deploy are able to start successfully, and are able to take on new traffic. aka register with the target group, pass health checks, etc. 



3. NEW: Validate Route53 Hosted Zone NS Delegation
Files: aws/route53.py, aws/acm.py
This was the root cause of our 15+ minute hang. The script creates DNS validation CNAME records in a Route53 hosted zone, but never checks whether that hosted zone is actually authoritative for the domain. If the domain registrar points to different nameservers (stale delegation from a deleted/recreated hosted zone), ACM will never see the validation records and validation hangs until timeout.
Fix: Before creating any DNS records, validate that the hosted zone's NS records match what the domain registrar has. This can be done by:
Looking up the hosted zone's NS records via Route53 API
Doing a public DNS lookup for the domain's NS records. specifically, this deploy script should update the ns records to be the correct ns records, and create a hosted zone if it doesn't exist. if these changes need to be made, ask the user to confirm these changes before making them. 