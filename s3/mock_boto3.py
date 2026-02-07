#!/usr/bin/env python3
"""
In-memory mock boto3 clients with the same interface as real AWS clients.
All state is stored in memory for testing without hitting AWS.
"""
import hashlib
import json
import time
from copy import deepcopy

try:
    from botocore.exceptions import ClientError
except ImportError:
    # Fallback if botocore not available
    class ClientError(Exception):
        def __init__(self, error_response, operation_name=None):
            self.response = error_response
            self.operation_name = operation_name


def _client_error(code, message=""):
    return ClientError({"Error": {"Code": code, "Message": message}}, "Operation")


class MockS3Client:
    """In-memory S3 client. State: buckets dict."""

    def __init__(self, state=None):
        self._buckets = state if state is not None else {}

    @property
    def state(self):
        return self._buckets

    def head_bucket(self, Bucket=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "Not Found")
        return {}

    def create_bucket(self, Bucket=None, CreateBucketConfiguration=None):
        if Bucket in self._buckets:
            raise _client_error("BucketAlreadyExists", "Bucket already exists")
        self._buckets[Bucket] = {
            "region": CreateBucketConfiguration["LocationConstraint"] if CreateBucketConfiguration else "us-east-1",
            "website": None,
            "public_access_block": None,
            "policy": None,
            "objects": {},
        }
        return {"Location": f"/{Bucket}"}

    def get_bucket_website(self, Bucket=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        cfg = self._buckets[Bucket].get("website")
        if cfg is None:
            raise _client_error("NoSuchWebsiteConfiguration", "No website config")
        return cfg

    def put_bucket_website(self, Bucket=None, WebsiteConfiguration=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        self._buckets[Bucket]["website"] = {"IndexDocument": WebsiteConfiguration.get("IndexDocument", {}), "ErrorDocument": WebsiteConfiguration.get("ErrorDocument", {})}
        return {}

    def get_public_access_block(self, Bucket=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        cfg = self._buckets[Bucket].get("public_access_block")
        if cfg is None:
            raise _client_error("NoSuchPublicAccessBlockConfiguration", "No block public access config")
        return {"PublicAccessBlockConfiguration": cfg}

    def put_public_access_block(self, Bucket=None, PublicAccessBlockConfiguration=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        self._buckets[Bucket]["public_access_block"] = dict(PublicAccessBlockConfiguration)
        return {}

    def get_bucket_policy(self, Bucket=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        policy = self._buckets[Bucket].get("policy")
        if policy is None:
            raise _client_error("NoSuchBucketPolicy", "No policy")
        return {"Policy": policy if isinstance(policy, str) else json.dumps(policy)}

    def put_bucket_policy(self, Bucket=None, Policy=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        self._buckets[Bucket]["policy"] = Policy
        return {}

    def get_paginator(self, operation_name):
        if operation_name != "list_objects_v2":
            raise ValueError(f"Unknown paginator: {operation_name}")

        class Paginator:
            def __init__(pag_self, buckets):
                pag_self._buckets = buckets

            def paginate(pag_self, Bucket=None, **kwargs):
                objs = pag_self._buckets.get(Bucket, {}).get("objects", {})
                contents = [{"Key": k} for k in objs]
                yield {"Contents": contents, "IsTruncated": False}

        return Paginator(self._buckets)

    def list_objects_v2(self, Bucket=None, **kwargs):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        objs = self._buckets[Bucket]["objects"]
        contents = [{"Key": k} for k in objs]
        return {"Contents": contents, "IsTruncated": False}

    def delete_objects(self, Bucket=None, Delete=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        for item in Delete.get("Objects", []):
            key = item.get("Key")
            if key in self._buckets[Bucket]["objects"]:
                del self._buckets[Bucket]["objects"][key]
        return {}

    def delete_bucket(self, Bucket=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        objs = self._buckets[Bucket].get("objects", {})
        if objs:
            raise _client_error("BucketNotEmpty", "The bucket you tried to delete is not empty")
        del self._buckets[Bucket]
        return {}

    def head_object(self, Bucket=None, Key=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        if Key not in self._buckets[Bucket]["objects"]:
            raise _client_error("404", "Not Found")
        obj = self._buckets[Bucket]["objects"][Key]
        body = obj["Body"]
        etag = hashlib.md5(body).hexdigest()
        return {"ETag": f'"{etag}"', "ContentLength": len(body)}

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        if Bucket not in self._buckets:
            raise _client_error("404", "NoSuchBucket")
        try:
            with open(Filename, "rb") as f:
                content = f.read()
        except FileNotFoundError:
            raise _client_error("NoSuchKey", f"File not found: {Filename}")
        self._buckets[Bucket]["objects"][Key] = {
            "Body": content,
            "ContentType": (ExtraArgs or {}).get("ContentType", "binary/octet-stream"),
        }
        return {}


class MockRoute53Client:
    """In-memory Route53 client. State: hosted_zones and record_sets."""

    def __init__(self, state=None):
        if state is not None:
            self._hosted_zones = state.get("hosted_zones", [])
            self._record_sets = state.get("record_sets", {})  # zone_id -> list of record dicts
        else:
            self._hosted_zones = []
            self._record_sets = {}

    @property
    def state(self):
        return {"hosted_zones": list(self._hosted_zones), "record_sets": dict(self._record_sets)}

    def get_paginator(self, operation_name):
        if operation_name != "list_hosted_zones":
            raise ValueError(f"Unknown paginator: {operation_name}")

        class Paginator:
            def __init__(pag_self, zones):
                pag_self._zones = zones

            def paginate(pag_self, **kwargs):
                yield {"HostedZones": pag_self._zones, "IsTruncated": False}

        return Paginator(self._hosted_zones)

    def list_hosted_zones(self, **kwargs):
        return {"HostedZones": self._hosted_zones, "IsTruncated": False}

    def list_resource_record_sets(self, HostedZoneId=None, StartRecordName=None, StartRecordType=None, MaxItems=None):
        records = self._record_sets.get(HostedZoneId, [])
        out = []
        for r in records:
            name = r.get("Name", "").rstrip(".")
            start = (StartRecordName or "").rstrip(".")
            if StartRecordName and not name.startswith(start):
                continue
            if StartRecordType and r.get("Type") != StartRecordType:
                continue
            out.append(r)
            if MaxItems and len(out) >= int(MaxItems):
                break
        return {"ResourceRecordSets": out, "IsTruncated": False}

    def change_resource_record_sets(self, HostedZoneId=None, ChangeBatch=None):
        if HostedZoneId not in self._record_sets:
            self._record_sets[HostedZoneId] = []
        for change in ChangeBatch.get("Changes", []):
            action = change["Action"]
            rr = change["ResourceRecordSet"]
            name = rr["Name"] if rr["Name"].endswith(".") else rr["Name"] + "."
            existing = [r for r in self._record_sets[HostedZoneId] if r.get("Name") == name and r.get("Type") == rr["Type"]]
            if action == "CREATE":
                if existing:
                    raise _client_error("InvalidChangeBatch", "ResourceRecordSetAlreadyExists")
                self._record_sets[HostedZoneId].append(deepcopy(rr))
            elif action == "UPSERT":
                if existing:
                    self._record_sets[HostedZoneId] = [r for r in self._record_sets[HostedZoneId] if not (r.get("Name") == name and r.get("Type") == rr["Type"])]
                self._record_sets[HostedZoneId].append(deepcopy(rr))
        return {"ChangeInfo": {"Id": "change-1", "Status": "PENDING"}}

    def add_hosted_zone(self, zone_id, name, ns_list=None):
        name = name.rstrip(".") if not name.endswith(".") else name[:-1]
        self._hosted_zones.append({"Id": zone_id, "Name": name + ".", "CallerReference": "test"})
        if ns_list:
            self._record_sets.setdefault(zone_id, []).append({
                "Name": name + ".",
                "Type": "NS",
                "TTL": 172800,
                "ResourceRecords": [{"Value": ns.rstrip(".") + "."} for ns in ns_list],
            })


class MockCloudFrontClient:
    """In-memory CloudFront client. State: distributions dict by id."""

    def __init__(self, state=None):
        if state is not None:
            self._distributions = state.setdefault("distributions", {})
            self._invalidations = state.setdefault("invalidations", [])
        else:
            self._distributions = {}
            self._invalidations = []
        self._next_id = 1

    @property
    def state(self):
        return {"distributions": dict(self._distributions), "invalidations": list(self._invalidations)}

    def get_paginator(self, operation_name):
        if operation_name != "list_distributions":
            raise ValueError(f"Unknown paginator: {operation_name}")

        class Paginator:
            def __init__(pag_self, dists):
                pag_self._dists = list(dists.values())

            def paginate(pag_self, **kwargs):
                yield {
                    "DistributionList": {"Items": pag_self._dists, "Quantity": len(pag_self._dists), "IsTruncated": False}
                }

        return Paginator(self._distributions)

    def list_distributions(self, **kwargs):
        items = list(self._distributions.values())
        return {"DistributionList": {"Items": items, "Quantity": len(items), "IsTruncated": False}}

    def get_distribution_config(self, Id=None):
        if Id not in self._distributions:
            raise _client_error("NoSuchDistribution", "Not found")
        d = self._distributions[Id]
        return {"DistributionConfig": deepcopy(d["Config"]), "ETag": d["ETag"]}

    def get_distribution(self, Id=None):
        if Id not in self._distributions:
            raise _client_error("NoSuchDistribution", "Not found")
        d = self._distributions[Id]
        return {"Distribution": {"Id": Id, "Status": d.get("Status", "Deployed"), "DomainName": d.get("DomainName", "d123.cloudfront.net"), "DistributionConfig": d["Config"]}}

    def create_distribution(self, DistributionConfig=None):
        dist_id = f"E{self._next_id}"
        self._next_id += 1
        aliases = DistributionConfig.get("Aliases", {}).get("Items", [])
        domain_name = f"d{dist_id.lower()}.cloudfront.net"
        self._distributions[dist_id] = {
            "Id": dist_id,
            "DomainName": domain_name,
            "Status": "Deployed",
            "Config": deepcopy(DistributionConfig),
            "Aliases": {"Items": aliases, "Quantity": len(aliases)},
            "ETag": f"etag-{dist_id}",
        }
        return {"Distribution": {"Id": dist_id, "DomainName": domain_name, "Status": "Deployed"}}

    def update_distribution(self, Id=None, DistributionConfig=None, IfMatch=None):
        if Id not in self._distributions:
            raise _client_error("NoSuchDistribution", "Not found")
        self._distributions[Id]["Config"] = deepcopy(DistributionConfig)
        self._distributions[Id]["ETag"] = f"etag-{Id}-updated"
        return {"Distribution": {"Id": Id, "Status": "InProgress"}}

    def create_invalidation(self, DistributionId=None, InvalidationBatch=None):
        inv_id = f"I{int(time.time())}"
        self._invalidations.append({"Id": inv_id, "DistributionId": DistributionId, "Paths": InvalidationBatch.get("Paths", {}).get("Items", [])})
        return {"Invalidation": {"Id": inv_id, "Status": "InProgress"}}

    def delete_distribution(self, Id=None, IfMatch=None):
        if Id not in self._distributions:
            raise _client_error("NoSuchDistribution", "Not found")
        del self._distributions[Id]
        return {}


class ResourceNotFoundException(ClientError):
    """ACM ResourceNotFoundException - same as botocore client."""
    pass


class MockACMClient:
    """In-memory ACM client. State: certificates dict by ARN."""

    def __init__(self, state=None, region="us-east-1"):
        self._region = region
        if state is not None:
            self._certs = state.setdefault("certificates", {})
        else:
            self._certs = {}
        self._next_arn_id = 1

    @property
    def exceptions(self):
        return type("Exceptions", (), {"ResourceNotFoundException": ResourceNotFoundException})()

    @property
    def state(self):
        return {"certificates": dict(self._certs)}

    def _make_arn(self, cert_id):
        return f"arn:aws:acm:{self._region}:123456789012:certificate/{cert_id}"

    def get_paginator(self, operation_name):
        if operation_name != "list_certificates":
            raise ValueError(f"Unknown paginator: {operation_name}")

        class Paginator:
            def __init__(pag_self, certs):
                pag_self._certs = list(certs.values())

            def paginate(pag_self, **kwargs):
                summary = [{"CertificateArn": c["CertificateArn"], "DomainName": c.get("DomainName", "")} for c in pag_self._certs]
                yield {"CertificateSummaryList": summary}

        return Paginator(self._certs)

    def describe_certificate(self, CertificateArn=None):
        if CertificateArn not in self._certs:
            raise ResourceNotFoundException({"Error": {"Code": "ResourceNotFoundException", "Message": "Certificate not found"}}, "DescribeCertificate")
        c = self._certs[CertificateArn]
        opts = c.get("DomainValidationOptions", [])
        # Return plain dicts/lists with string values only (no nested dict refs) so acm module doesn't hit unhashable type
        opts_copy = []
        for o in opts:
            rr = o.get("ResourceRecord") or {}
            opts_copy.append({
                "DomainName": str(o.get("DomainName", "")),
                "ValidationStatus": str(o.get("ValidationStatus", "")),
                "ResourceRecord": {"Name": str(rr.get("Name", "")), "Type": str(rr.get("Type", "")), "Value": str(rr.get("Value", ""))},
            })
        return {"Certificate": {"CertificateArn": CertificateArn, "DomainName": str(c.get("DomainName", "")), "Status": str(c.get("Status", "PENDING_VALIDATION")), "DomainValidationOptions": opts_copy, "SubjectAlternativeNames": [str(x) for x in c.get("SubjectAlternativeNames", [])]}}

    def request_certificate(self, DomainName=None, ValidationMethod=None, SubjectAlternativeNames=None):
        cert_id = str(self._next_arn_id)
        self._next_arn_id += 1
        arn = self._make_arn(cert_id)
        self._certs[arn] = {
            "CertificateArn": arn,
            "DomainName": DomainName,
            "Status": "PENDING_VALIDATION",
            "DomainValidationOptions": [{"DomainName": DomainName, "ValidationStatus": "PENDING_VALIDATION", "ResourceRecord": {"Name": f"_abc.{DomainName}.", "Type": "CNAME", "Value": "xyz.acm-validations.aws."}}],
            "SubjectAlternativeNames": SubjectAlternativeNames or [],
        }
        return {"CertificateArn": arn}


class MockSTSClient:
    """In-memory STS client."""

    def __init__(self, account_id="123456789012", user_id="test-user", arn="arn:aws:iam::123456789012:user/test"):
        self._account_id = account_id
        self._user_id = user_id
        self._arn = arn

    def get_caller_identity(self):
        return {"Account": self._account_id, "UserId": self._user_id, "Arn": self._arn}


class MockSession:
    """Mock boto3.Session that returns in-memory clients. State is shared per service type."""

    def __init__(self, profile_name=None, region_name=None):
        self.profile_name = profile_name
        self.region_name = region_name
        self._s3_state = {}
        self._route53_state = {}
        self._cloudfront_state = {}
        self._acm_state = {}
        self._sts = MockSTSClient()

    def client(self, service_name, region_name=None):
        region = region_name or self.region_name
        if service_name == "s3":
            return MockS3Client(self._s3_state)
        if service_name == "route53":
            return MockRoute53Client(self._route53_state)
        if service_name == "cloudfront":
            return MockCloudFrontClient(self._cloudfront_state)
        if service_name == "acm":
            return MockACMClient(self._acm_state, region=region or "us-east-1")
        if service_name == "sts":
            return self._sts
        raise ValueError(f"Unknown service: {service_name}")

    def reset(self):
        self._s3_state.clear()
        self._route53_state.clear()
        self._cloudfront_state.clear()
        self._acm_state.clear()

    def seed_route53_hosted_zone(self, zone_id, name, ns_list=None):
        """Add a hosted zone for tests (e.g. find_hosted_zone).
        If ns_list is provided, seeds the zone's NS record set so get_hosted_zone_ns works.
        """
        name = name.rstrip(".") if name.endswith(".") else name
        self._route53_state.setdefault("hosted_zones", []).append(
            {"Id": zone_id, "Name": name + ".", "CallerReference": "test"}
        )
        self._route53_state.setdefault("record_sets", {})
        if ns_list:
            record_sets = self._route53_state["record_sets"]
            record_sets.setdefault(zone_id, []).append({
                "Name": name + ".",
                "Type": "NS",
                "TTL": 172800,
                "ResourceRecords": [{"Value": ns.rstrip(".") + "."} for ns in ns_list],
            })

    def seed_acm_certificate(self, arn, domain, status="ISSUED"):
        """Add an ACM certificate for tests."""
        self._acm_state.setdefault("certificates", {})[arn] = {
            "CertificateArn": arn,
            "DomainName": domain,
            "Status": status,
            "DomainValidationOptions": [],
            "SubjectAlternativeNames": [domain],
        }
