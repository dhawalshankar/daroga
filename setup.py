




















from setuptools import setup, find_packages

setup(
    name="daroga",
    version="2.0.0",
    description="DAROGA — Autonomous EC2 to AWS Lambda Migration Auditor",
    py_modules=["agent"],
    packages=["daroga"],
    install_requires=[
        "groq>=0.11.0",
        "openai>=1.0.0",
        "anthropic>=0.20.0",
        "boto3>=1.34.0",
        "pyyaml>=6.0.0",
        "playwright>=1.40.0",
    ],
    entry_points={
        "console_scripts": [
            "daroga=agent:daroga_main",
            "aws-migrator=agent:main",
            "aws_migrator=agent:main",
        ],
    },
    python_requires=">=3.10",
)
