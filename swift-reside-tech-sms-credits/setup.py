"""
Setup script for swift-reside-tech-sms-credits package
"""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="swift-reside-tech-sms-credits",
    version="1.0.0",
    author="Swift Reside Tech",
    author_email="info@swiftresidetech.com",
    description="Django package for SMS credits management with multi-tenancy and KCB payment integration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/swiftresidetech/swift-reside-tech-sms-credits",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Framework :: Django",
        "Framework :: Django :: 3.2",
        "Framework :: Django :: 4.0",
        "Framework :: Django :: 4.1",
        "Framework :: Django :: 4.2",
    ],
    python_requires=">=3.8",
    install_requires=[
        "Django>=3.2",
        "requests>=2.25.0",
        "cryptography>=3.4.0",
    ],
    include_package_data=True,
    zip_safe=False,
)

