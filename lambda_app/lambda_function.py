"""
AWS Lambda Serverless Entrypoint
Bridges Amazon API Gateway v2 HTTP events to WSGI Flask application.
"""
import logging
from apig_wsgi import make_lambda_handler
from app import app

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# High-performance WSGI adapter
lambda_handler = make_lambda_handler(app)
