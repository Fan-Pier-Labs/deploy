
also: can we make this faster? I think it can be a lot faster than this.

3. NEW: Validate Route53 Hosted Zone NS Delegation
Files: aws/route53.py, aws/acm.py
This was the root cause of our 15+ minute hang. The script creates DNS validation CNAME records in a Route53 hosted zone, but never checks whether that hosted zone is actually authoritative for the domain. If the domain registrar points to different nameservers (stale delegation from a deleted/recreated hosted zone), ACM will never see the validation records and validation hangs until timeout.
Fix: Before creating any DNS records, validate that the hosted zone's NS records match what the domain registrar has. This can be done by:
Looking up the hosted zone's NS records via Route53 API
Doing a public DNS lookup for the domain's NS records
If they don't match, print a clear error with instructions
4. HTTP Test Should Accept CloudFront URL as Full Success
File: aws/deploy.py lines 314-419, specifically test_deployment_http_requests()
The test function requires the custom domain to resolve, but DNS propagation (especially after an NS change) can take minutes to hours. The function uses urllib.request.urlopen which relies on the container's local DNS resolver, which may cache stale NXDOMAIN responses.
Fix:
If the CloudFront URL (d*.cloudfront.net) returns 200, count that as a full success and exit early
Only treat domain URL tests as informational/optional
Alternatively, use --resolve-style DNS override to test the domain against CloudFront IPs directly
5. Duplicate boto3 Import
File: aws/deploy.py lines 8 and 14
import boto3  # line 8# ...import boto3  # line 14 (duplicate)
And again inside deploy_production_public_app at line 226:
import boto3  # line 226 (another duplicate)
Fix: Remove the duplicates, keep only the top-level import.
6. No CloudFront Deployment Wait
File: aws/cloudfront.py lines 189-214
The function wait_for_cloudfront_deployment() exists but is never called anywhere in deploy.py. The script prints "Distribution may take 15-20 minutes to deploy" and moves on. Meanwhile, the HTTP tests fail because CloudFront isn't ready.
Fix: Optionally call wait_for_cloudfront_deployment() before running HTTP tests, or at least between creating the distribution and running tests.
7. No Graceful Recovery from Partial Deployment State
When the deploy failed mid-way (certificate validation timeout), the ALB, target group, listeners, and security groups were all created but CloudFront was not. On the next run, the script correctly found and reused the existing resources, but this was by luck rather than design.
Fix: Consider adding:
A state file that tracks which resources were created
A --cleanup flag to tear down partial deployments
Better error messages when the script detects partial state ("ALB exists but no CloudFront distribution found - resuming from certificate step")
8. Security Group Port Mismatch in Lightweight Mode
File: aws/vpc.py lines 62-79
When creating the initial security group, only ports 80 and 443 are opened. In lightweight mode, the container serves on port 8080, so deploy_lightweight_public_app() has to add port 8080 as a separate step. This works but is fragile.
Fix: If mode is lightweight, include the container port in the initial security group creation. If mode is production, only the ALB security group needs 80/443 (which is already correct).
9. Environment Variables Support is Undocumented
File: aws/config.py line 96, aws/ecs.py lines 76-81
The config loader supports an environment key in deploy.yaml that gets passed as container environment variables:
config.py
Lines 96-96
            'environment': config.get('environment', {}),
But the example deploy.yaml template doesn't show this. For our app, we need NODE_ENV=production and potentially the OPENAI_API_KEY.
Fix: Add a commented example in the default deploy.yaml template:
# environment:#   NODE_ENV: "production"#   MY_API_KEY: "secret-value"
10. ACM Certificate Requested Before DNS Validation Records Are Available
File: aws/acm.py lines 148-176, get_certificate_validation_records()
After requesting a new certificate, get_certificate_validation_records() is called immediately. However, ACM sometimes takes a few seconds to populate the DomainValidationOptions with ResourceRecord entries. If the records aren't available yet, the function returns an empty list and the script falls through to a "manual validation" warning instead of retrying.
Fix: Add a short retry loop (3-5 attempts with 2-second delays) in get_certificate_validation_records() to wait for ACM to populate the validation records
