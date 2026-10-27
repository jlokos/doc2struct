from setuptools import setup, find_packages

setup(
    name="doc2struct",
    version="0.1.0",
    packages=find_packages(),
    package_data={'doc2struct': ['rules/presets/*.json']},
    install_requires=[],
    extras_require={'parquet': ['polars']},
)