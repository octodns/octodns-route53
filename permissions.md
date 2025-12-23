# AWS Permissions Required for octodns-route53

This document lists all AWS IAM permissions required to use octodns-route53.

## Overview

Octodns-route53 requires permissions for three AWS services:
- **Route53**: for managing DNS zones and records
- **EC2**: for instance discovery (optional, if you use Ec2Source)
- **ELBv2**: for load balancer discovery (optional, if you use ElbSource)

## IAM Policy Examples

### Minimal Configuration (read-only)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:ListHostedZonesByName",
        "route53:ListResourceRecordSets",
        "route53:ListHealthChecks"
      ],
      "Resource": "*"
    }
  ]
}
```

### Full Configuration (read/write)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:ListHostedZonesByName",
        "route53:CreateHostedZone",
        "route53:ListResourceRecordSets",
        "route53:ChangeResourceRecordSets",
        "route53:ListHealthChecks",
        "route53:CreateHealthCheck",
        "route53:DeleteHealthCheck",
        "route53:ChangeTagsForResource"
      ],
      "Resource": "*"
    }
  ]
}
```

### Configuration with EC2 and ELB

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:ListHostedZonesByName",
        "route53:CreateHostedZone",
        "route53:ListResourceRecordSets",
        "route53:ChangeResourceRecordSets",
        "route53:ListHealthChecks",
        "route53:CreateHealthCheck",
        "route53:DeleteHealthCheck",
        "route53:ChangeTagsForResource"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTags"
      ],
      "Resource": "*"
    }
  ]
}
```

## Permissions by Use Case

| Use Case | Required Permissions |
|----------|---------------------|
| **Read-only** (viewing zones and records) | `route53:ListHostedZones`, `route53:ListHostedZonesByName`, `route53:ListResourceRecordSets` |
| **Record management** (without zone creation) | All Route53 permissions except `route53:CreateHostedZone` |
| **Full management** (with zone creation) | All Route53 permissions |
| **With EC2 discovery** | Route53 permissions + `ec2:DescribeInstances` |
| **With ELB discovery** | Route53 permissions + `elasticloadbalancing:DescribeLoadBalancers`, `elasticloadbalancing:DescribeTags` |

## Route53 Permissions (required)

These permissions are required for the main Route53 provider.

### 1. Hosted Zone Management

#### `route53:ListHostedZones`
- **Method**: `Route53Provider.update_r53_zones()`
- **Usage**: Lists all hosted zones in your AWS account
- **Context**: Loads and caches all available zones

#### `route53:ListHostedZonesByName`
- **Method**: `Route53Provider._get_zone_id_by_name()`
- **Usage**: Retrieves hosted zones by DNS name
- **Context**: Used to find a specific zone by its name

#### `route53:CreateHostedZone`
- **Method**: `Route53Provider.update_r53_zones()`
- **Usage**: Creates a new hosted zone if it doesn't exist
- **Context**: Only required if you want to automatically create new zones

### 2. DNS Record Management

#### `route53:ListResourceRecordSets`
- **Method**: `Route53Provider._load_records()`
- **Usage**: Lists all DNS records in a hosted zone
- **Context**: Loads the current state of DNS records for comparison and synchronization

#### `route53:ChangeResourceRecordSets`
- **Method**: `Route53Provider._really_apply()`
- **Usage**: Creates, modifies, or deletes DNS records
- **Context**: Applies DNS changes (creates, updates, deletes)

### 3. Health Check Management

#### `route53:ListHealthChecks`
- **Method**: `Route53Provider.health_checks`
- **Usage**: Lists all Route53 health checks
- **Context**: Loads existing health checks for records with monitoring

#### `route53:CreateHealthCheck`
- **Method**: `Route53Provider._create_health_check()`
- **Usage**: Creates new health checks to monitor DNS records
- **Context**: Required for dynamic records with health checking

#### `route53:DeleteHealthCheck`
- **Method**: `Route53Provider._gc_health_checks()`
- **Usage**: Deletes obsolete health checks
- **Context**: Cleanup of health checks that are no longer in use

#### `route53:ChangeTagsForResource`
- **Method**: `Route53Provider._create_health_check()`
- **Usage**: Adds tags to health checks
- **Context**: Tags health checks with a name for easier identification in the AWS console

## EC2 Permissions (optional)

These permissions are only required if you use `Ec2Source` to automatically discover EC2 instances.

#### `ec2:DescribeInstances`
- **Method**: `Ec2Source.instances`
- **Usage**: Lists and retrieves EC2 instance information
- **Context**: Enables automatic creation of DNS records based on EC2 instances and their tags

## ELBv2 Permissions (optional)

These permissions are only required if you use `ElbSource` to automatically discover load balancers.

#### `elasticloadbalancing:DescribeLoadBalancers`
- **Method**: `ElbSource.lbs`
- **Usage**: Lists all Application/Network Load Balancers
- **Context**: Enables retrieval of load balancer information to create DNS records

#### `elasticloadbalancing:DescribeTags`
- **Method**: `ElbSource.lbs`
- **Usage**: Retrieves tags associated with load balancers
- **Context**: Enables identification of FQDNs from load balancer tags

## Important Notes

1. **Global resources**: Most Route53 actions require `"Resource": "*"` because Route53 is a global service.

2. **Health checks**: If you don't use health checks (no dynamic records), you can omit:
   - `route53:ListHealthChecks`
   - `route53:CreateHealthCheck`
   - `route53:DeleteHealthCheck`
   - `route53:ChangeTagsForResource`

3. **Zone creation**: If you manage your zones manually via the AWS console, you can omit `route53:CreateHostedZone`.

4. **Zone deletion**: octodns-route53 **never** deletes hosted zones. The `route53:DeleteHostedZone` permission is therefore not required. Zone deletion must be performed manually via the AWS console or AWS CLI.

5. **Dry-run mode**: Even when `octodns-sync`, read permissions are required to load the current state.

6. **Optional sources**: EC2 and ELBv2 permissions are only required if you explicitly configure `Ec2Source` or `ElbSource` in your octoDNS configuration.
