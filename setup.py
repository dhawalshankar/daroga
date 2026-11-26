from setuptools import setup

setup(
    name="aws-migrator",
    version="1.0.0",
    description="Autonomous EC2 to AWS Lambda Migration Agent CLI",
    py_modules=["agent"],
    install_requires=[
        "groq>=0.11.0",
        "openai>=1.0.0",
        "anthropic>=0.20.0",
    ],
    entry_points={
        "console_scripts": [
            "aws-migrator=agent:main",
            "aws_migrator=agent:main",
        ],
    },
    python_requires=">=3.10",
)
