
- [ ] add the ability to deploy to a specific ec2 instance, such that you only have ssh access and nothing else to that instance (dev servers)

- [ ] Test the vercel deployment option.

- [ ] Add the ability to search all cloud accounts (eg cloudflare, gcp, azure, porkbun) for a domain, and then update the dns settings in that respective cloud account but use the primary cloud account the user specified for the https cert, cdn, load balancer, app server, etc


- [ ] with s3, is it possible to only upload files that changed? 

- [x] when you deploy to s3, revoke the entire cloudfront cdn cache for the relevant cdn
- [ ] i need a way to teardown all relevant infrastructure so it can be re-built on next deploy. this can be used to solve bugs, or times where infra that was already set up is bugged out


- [ ] migrate to buildx Buildx is Docker’s CLI for the BuildKit builder and gives you explicit control over platform and cache. Your deploy uses --platform=linux/amd64 for Fargate, but Docker’s default cache doesn’t separate layers by architecture, so a build on ARM64 (e.g. your Mac) can cache ARM64 layers and then fail when the same cache is reused for an AMD64 build inside the container (or the other way around). With Buildx you can send cache to architecture-specific locations (e.g. --cache-to type=local,dest=./.buildx-cache-amd64 or a registry tag like buildcache:amd64), and use the matching --cache-from when building, so each platform (amd64 vs arm64) has its own cache and they never get mixed. That way you can run the same deploy command both on your host and inside the dev container without platform/cache conflicts, and still get fast, correct builds.
