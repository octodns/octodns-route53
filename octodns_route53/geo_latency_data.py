#
# -*- coding: utf-8 -*-
#
# This file import geodata and add AWS region if new location added please complete this file
#
# source from : https://docs.aws.amazon.com/fr_fr/AWSEC2/latest/UserGuide/using-regions-availability-zones.html

from octodns.record.geo_data import geo_data

# North America
geo_data['NA']['region'] = 'us-east-1'
geo_data['NA']['US']['region'] = 'us-east-1'
geo_data['NA']['US']['provinces']['VA']['region'] = 'us-east-1'
geo_data['NA']['US']['provinces']['OH']['region'] = 'us-east-2'
geo_data['NA']['US']['provinces']['CA']['region'] = 'us-west-1'
geo_data['NA']['US']['provinces']['OR']['region'] = 'us-west-2'

# Africa
geo_data['AF']['region'] = "af-south-1"
geo_data['AF']['ZA']['region'] = "af-south-1"

# Asia Pacific

geo_data['AS']['HK']['region'] = 'ap-east-1'
geo_data['AS']['IN']['region'] = 'ap-south-1'
geo_data['AS']['PK']['region'] = 'ap-south-2'
geo_data['AS']['SG']['region'] = 'ap-southeast-1'
geo_data['OC']['AU']['region'] = 'ap-southeast-2'
geo_data['AS']['ID']['region'] = 'ap-southeast-3'
## australia too but fallback to nearest (New Zealand) to select this region
geo_data['OC']['NZ']['region'] = 'ap-southeast-4'
geo_data['AS']['JP']['region'] = 'ap-northeast-1'
geo_data['AS']['KR']['region'] = 'ap-northeast-2'
## japan too but fallback to nearest (Taiwan) to select this region
geo_data['AS']['TW']['region'] = 'ap-northeast-3'

# Canada
geo_data['NA']['CA']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['AB']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['BC']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['MB']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['NB']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['NL']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['NS']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['NT']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['NU']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['ON']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['PE']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['QC']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['SK']['region'] = 'ca-central-1'
geo_data['NA']['CA']['provinces']['YT']['region'] = 'ca-central-1'


# Europe
geo_data['EU']['region'] = 'eu-west-1'
geo_data['EU']['IE']['region'] = 'eu-west-1'
geo_data['EU']['GB']['region'] = 'eu-west-2'
geo_data['EU']['FR']['region'] = 'eu-west-3'
geo_data['EU']['IT']['region'] = 'eu-south-1'
geo_data['EU']['ES']['region'] = 'eu-south-2'
geo_data['EU']['SE']['region'] = 'eu-north-1'
geo_data['EU']['DE']['region'] = 'eu-central-1'
geo_data['EU']['SE']['region'] = 'eu-central-2'


# Middle East
geo_data['AS']['BH']['region'] = "me-south-1"
geo_data['AS']['AE']['region'] = "me-central-1"

# South America
geo_data['SA']['region'] = "sa-east-1"
geo_data['SA']['BR']['region'] = "sa-east-1"
