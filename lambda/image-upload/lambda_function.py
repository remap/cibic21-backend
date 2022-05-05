import os
import mimetypes
import boto3
import base64
from common.cibic_common import *

s3 = boto3.client('s3')

def lambda_handler(event, context):
    mimetypes.init()
    requestReply = {}

    try:
        print ('event data ' + str(event))

        stage = event['requestContext']['stage']

        if event['httpMethod'] == 'POST':
            requestBody = json.loads(event['body'])

            if 'name' in requestBody and 'file' in requestBody:
                name = requestBody['name']
                imageBase64 = requestBody['file']
                image = base64.b64decode(imageBase64)

                # Get the ContentType for the filename extension.
                _, extension = os.path.splitext(name)
                contentType= 'binary/octet-stream'
                try:
                    contentType = mimetypes.types_map[extension]
                except:
                    # File extension not recognized.
                    pass

                print('Saving in S3 bucket: file size ' + str(len(image)) + ', name: ' + name)
                s3.put_object(Bucket=CibicResources.S3Bucket.JournalingImages,
                              Key=name, Body=image, ContentType=contentType)

                # Give the response to enable CORS.
                requestReply = {
                    'statusCode': 200,
                    'headers': { "Access-Control-Allow-Origin": "*" },
                    'body': 'Message processed'
                }
            else:
                requestReply = lambdaReply(420, "Need 'name' and 'file' in body")
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    return requestReply
