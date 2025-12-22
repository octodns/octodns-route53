# AWS Permissions Required for octodns-route53

This document lists all AWS IAM permissions required to use octodns-route53.

## Overview

Octodns-route53 requires permissions for three AWS services:
- **Route53**: for managing DNS zones and records
- **EC2**: for instance discovery (optional, if you use Ec2Source)
- **ELBv2**: for load balancer discovery (optional, if you use ElbSource)

## Route53 Permissions (required)

These permissions are required for the main Route53 provider.

### 1. Hosted Zone Management

#### `route53:ListHostedZones`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L749)
- **Usage**: Lists all hosted zones in your AWS account
- **Context**: Loads and caches all available zones

#### `route53:ListHostedZonesByName`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L716)
- **Usage**: Retrieves hosted zones by DNS name
- **Context**: Used to find a specific zone by its name

#### `route53:CreateHostedZone`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L791)
- **Usage**: Creates a new hosted zone if it doesn't exist
- **Context**: Only required if you want to automatically create new zones

### 2. DNS Record Management

#### `route53:ListResourceRecordSets`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L945)
- **Usage**: Lists all DNS records in a hosted zone
- **Context**: Loads the current state of DNS records for comparison and synchronization

#### `route53:ChangeResourceRecordSets`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L1785)
- **Usage**: Creates, modifies, or deletes DNS records
- **Context**: Applies DNS changes (creates, updates, deletes)

### 3. Health Check Management

#### `route53:ListHealthChecks`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L1251)
- **Usage**: Lists all Route53 health checks
- **Context**: Loads existing health checks for records with monitoring

#### `route53:CreateHealthCheck`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L1446)
- **Usage**: Creates new health checks to monitor DNS records
- **Context**: Required for dynamic records with health checking

#### `route53:DeleteHealthCheck`
- **Files**: 
  - [octodns_route53/provider.py](octodns_route53/provider.py#L1506)
  - [octodns_route53/provider.py](octodns_route53/provider.py#L1513)
- **Usage**: Deletes obsolete health checks
- **Context**: Cleanup of health checks that are no longer in use

#### `route53:ChangeTagsForResource`
- **File**: [octodns_route53/provider.py](octodns_route53/provider.py#L1455)
- **Usage**: Adds tags to health checks
- **Context**: Tags health checks with a name for easier identification in the AWS console

## EC2 Permissions (optional)

Ces permissions sont nécessaires uniquement si vous utilisez `Ec2Source` pour découvrir automatiquement les instances EC2.

#### `ec2:DescribeInstances`
- **File**: [octodns_route53/source.py](octodns_route53/source.py#L67)
- **Usage**: Lists and retrieves EC2 instance information
- **Context**: Enables automatic creation of DNS records based on EC2 instances and their tags

## ELBv2 Permissions (optional)

These permissions are only required if you use `ElbSource` to automatically discover load balancers.

#### `elasticloadbalancing:DescribeLoadBalancers`
- **File**: [octodns_route53/source.py](octodns_route53/source.py#L248)
- **Usage**: Lists all Application/Network Load Balancers
- **Context**: Enables retrieval of load balancer information to create DNS records

#### `elasticloadbalancing:DescribeTags`
- **File**: [octodns_route53/source.py](octodns_route53/source.py#L260)
- **Usage**: Retrieves tags associated with load balancers
- **Context**: Enables identification of FQDNs from load balancer tags

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

## Important Notes

1. **Ressources globales** : La plupart des actions Route53 nécessitent `"Resource": "*"` car Route53 est un service global.

2. **Health checks** : Si vous n'utilisez pas de health checks (pas d'enregistrements dynamiques), vous pouvez omettre :
   - `route53:ListHealthChecks`
   - `route53:CreateHealthCheck`
   - `route53:DeleteHealthCheck`
   - `route53:ChangeTagsForResource`

3. **Création de zones** : Si vous gérez vos zones manuellement via la console AWS, vous pouvez omettre `route53:CreateHostedZone`.

4. **Suppression de zones** : octodns-route53 ne supprime **jamais** de zones hébergées. La permission `route53:DeleteHostedZone` n'est donc pas nécessaire. La suppression de zones doit être effectuée manuellement via la console AWS ou AWS CLI.

5. **Mode dry-run** : Même en mode `--dryrun`, les permissions de lecture sont nécessaires pour charger l'état actuel.

6. **Sources optionnelles** : Les permissions EC2 et ELBv2 ne sont nécessaires que si vous configurez explicitement `Ec2Source` ou `ElbSource` dans votre configuration octoDNS.

## Références de code

Toutes les références aux lignes de code pointent vers la branche `main` du repository. Les numéros de ligne peuvent changer avec les mises à jour du code.
