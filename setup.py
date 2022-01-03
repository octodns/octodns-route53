from setuptools import setup


def descriptions():
    with open('README.md') as fh:
        ret = fh.read()
        first = ret.split('\n', 1)[0].replace('#', '')
        return first, ret


def version():
    with open('octodns_route53/__init__.py') as fh:
        for line in fh:
            if line.startswith('__VERSION__'):
                return line.split("'")[1]


description, long_description = descriptions()

setup(
    author='Ross McFarland',
    author_email='rwmcfa1@gmail.com',
    description=description,
    license='MIT',
    long_description=long_description,
    long_description_content_type='text/markdown',
    name='octodns-route53',
    packages=('octodns_route53',),
    python_requires='>=3.6',
    install_requires=('octodns>=0.9.14', 'boto>=1.20.26'),
    url='https://github.com/octodns/octodns-route53',
    version=version(),
    tests_require=[
        'mock>=4.0.3',
        'nose',
        'nose-no-network',
    ],
)
