#
#
#

from .geo_latency_data import geo_data


class GeoLatency(object):
    @classmethod
    def parse(cls, code):
        pieces = code.split('-')
        continent_code = pieces[0]
        try:
            country_code = pieces[1]
        except IndexError:
            country_code = None
        try:
            province_code = pieces[2]
        except IndexError:
            province_code = None

        region = None
        if continent_code in geo_data:
            if (
                country_code is not None
                and country_code in geo_data[continent_code]
            ):
                if (
                    province_code is not None
                    and province_code
                    in geo_data[continent_code][country_code]["provinces"]
                ):
                    if (
                        'region'
                        in geo_data[continent_code][country_code]["provinces"][
                            province_code
                        ]
                    ):
                        region = geo_data[continent_code][country_code][
                            "provinces"
                        ][province_code]['region']
                else:
                    if 'region' in geo_data[continent_code][country_code]:
                        region = geo_data[continent_code][country_code][
                            'region'
                        ]
            else:
                if 'region' in geo_data[continent_code]:
                    region = geo_data[continent_code]['region']

        return {
            'continent_code': continent_code,
            'country_code': country_code,
            'province_code': province_code,
            'region': region,
        }
