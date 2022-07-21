# This Lambda is for the API to fetch the research data and export as an Excel file.

from common.cibic_common import *
import os
import io
import json
import psycopg2
from datetime import datetime
import boto3
from boto3.dynamodb.conditions import Attr
import pandas as pd

pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']

dynamoDbResource = boto3.resource('dynamodb')
debug_s3 = boto3.client('s3')

def lambda_handler(event, context):
    journalsTable = dynamoDbResource.Table(CibicResources.DynamoDB.JournalingRequests)

    try:
        #conn = psycopg2.connect(host=pgServer, database=pgDbName,
        #                        user=pgUsername, password=pgPassword)
        #cur = conn.cursor()
        #conn.commit()
        #cur.close()

        response = journalsTable.scan(
          FilterExpression = Attr('type').eq('reflection') &
                             Attr('processed').eq(True)
        )
        items = response['Items']
        print('Processing ' + str(len(items)) + ' journal entries.')
        rows = []
        expectedPrompts = [
          'Rate your commute satisfaction:',
          'Select all the characteristics of your ride:',
          'Describe your ride with one word or short phrase:',
          'What color best expresses how you feel about your last CiBiC ride?'
        ]
        for item in items:
            try:
                body = json.loads(item['body'])
            except:
                continue

            answers = body.get('answers')
            journal = body.get('journal')
            if body.get('userId') == None or body.get('role') == None or answers == None or journal == None:
                continue
            if len(body['userId']) < 10:
                # Assume that a short user ID is for testing.
                continue

            row = [body['userId'],
                   body['role'],
                   # Pandas wants us to strip the time zone from the datetime.
                   datetime.fromisoformat(item['timestamp']).replace(tzinfo=None)]
                   
            for i in range(len(expectedPrompts)):
                if i >= len(answers) or i >= len(journal):
                    # The journal doesn't have enough responses.
                    row.append("")
                elif journal[i]['prompt'] != expectedPrompts[i]:
                    # The journal question has changed.
                    row.append("")
                else:
                    row.append(answers[i])

            rows.append(row)

        frame1 = pd.DataFrame(
            rows,
            columns=(['User ID', 'Role', 'Date (UTC)'] + expectedPrompts))
        #frame2 = pd.DataFrame([[1, 2], [3, 4]], columns=['col 1', 'col 2'])

        with io.BytesIO() as output:
            with pd.ExcelWriter(output) as writer:
                frame1.to_excel(writer, sheet_name='Daily Journals Report', index=False)
                #frame2.to_excel(writer, sheet_name='Monthly Survey Report', index=False)
            excel = output.getvalue()
        print('Debug Excel output file size ' + str(len(excel)))
        # TODO: When done testing, remove Lambda permissions to S3.
        debug_s3.put_object(Bucket=CibicResources.S3Bucket.JournalingImages,
                            Key='debug_research.xlsx', Body=excel)

        return lambdaReply(200, {})
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))
