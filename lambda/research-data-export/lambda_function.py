# This Lambda is for the API to fetch the research data and export as an Excel file.

from common.cibic_common import *
import os
import io
import json
import base64
import psycopg2
from datetime import datetime
import boto3
from boto3.dynamodb.conditions import Attr
import pandas as pd

pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
cibicEmail = 'support@cibic.bike'

dynamoDbResource = boto3.resource('dynamodb')
sesClient = boto3.client('ses')
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
        expectedSatisfactionOptions = [ 'Terrible', 'Bad', 'Okay', 'Good', 'Great' ]

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

            # Pandas wants us to strip the time zone from the datetime.
            timestamp = datetime.fromisoformat(item['timestamp']).replace(tzinfo=None)
            if timestamp < datetime.fromisoformat('2022-08-01T00:00:00'):
                # Older journal entries have a different format.
                continue

            row = [body['userId'], body['role'], timestamp]
                   
            for i in range(len(expectedPrompts)):
                if i >= len(answers) or i >= len(journal):
                    # The journal doesn't have enough responses.
                    row.append('')
                    continue

                prompt = journal[i]['prompt']['en']
                if prompt != expectedPrompts[i]:
                    # The journal question has changed.
                    row.append("")
                    continue

                answer = answers[i]
                if prompt == 'Rate your commute satisfaction:':
                    answerIndex = int(answer)
                    answerText = journal[i]['options'][answerIndex]['label']['en']
                    expectedAnswerText = expectedSatisfactionOptions[answerIndex]
                    if answerText != expectedAnswerText:
                        # The prompt at the index for this answer doesn't match the expected prompt.
                        answer = ''

                elif prompt == 'Select all the characteristics of your ride:':
                    formattedAnswer = ''
                    for item in answer:
                        if formattedAnswer != '':
                            formattedAnswer += ', '
                        formattedAnswer += item.get('en', '')

                    answer = formattedAnswer

                row.append(answer)

            rows.append(row)

        headers = [] + expectedPrompts
        # Show the satisfaction options numbers in the header
        for i in range(len(expectedSatisfactionOptions)):
            headers[0] += (', ' if i > 0 else ' ') + str(i) + ' = ' + expectedSatisfactionOptions[i]
        headers[3] = 'Color Wheel (for interpretive cartography purposes)'

        frame1 = pd.DataFrame(
            rows,
            columns=(['User ID', 'Role', 'Date (UTC)'] + headers))
        #frame2 = pd.DataFrame([[1, 2], [3, 4]], columns=['col 1', 'col 2'])

        with io.BytesIO() as output:
            with pd.ExcelWriter(output) as writer:
                frame1.to_excel(writer, sheet_name='Daily Journals Report', index=False)
                #frame2.to_excel(writer, sheet_name='Monthly Survey Report', index=False)
            excel = output.getvalue()
        print('Debug Excel output file size ' + str(len(excel)))
        ## TODO: When done testing, remove Lambda permissions to S3.
        #debug_s3.put_object(Bucket=CibicResources.S3Bucket.JournalingImages,
        #                    Key='CiBiC_Data_Report.xlsx', Body=excel)
        emailAttachment(cibicEmail, 'jefft0@remap.ucla.edu',
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'CiBiC_Data_Report.xlsx', excel)

        return lambdaReply(200, {})
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

def emailAttachment(fromEmail, toEmail, contentType, filename, fileBytes):
    """
    Send and email with a base64-encoded attachment of the fileBytes.
    """
    response = sesClient.send_raw_email(
        RawMessage = {
          'Data':
'''From: ''' + fromEmail + '''
To: ''' + toEmail + '''
Subject: ''' + filename + '''
MIME-Version: 1.0
Content-type: Multipart/Mixed; boundary="NextPart"

--NextPart
Content-Type: text/plain

See the attached file: ''' + filename + '''

--NextPart
Content-Type: ''' + contentType + '''; name="''' + filename + '''"
Content-Disposition: attachment; filename="''' + filename + '''"
Content-Transfer-Encoding: base64

''' + base64Encode(fileBytes, True) + '''
--NextPart--''',
        }
    )

def base64Encode(input, addNewlines = False):
    """
    Encode the input as base64.

    :param input: The bytes to encode.
    :type bytes input: The byte array to encode.
    :param bool addNewlines: (optional) If True, add newlines to the
      encoding (good for writing to a file).  If omitted or False, do not
      add newlines.
    :return: The encoding.
    :rtype: str
    """
    base64Str = base64.b64encode(input)
    if not type(base64Str) is str:
        base64Str = "".join(map(chr, base64Str))

    if not addNewlines:
        return base64Str

    result = ""
    i = 0
    while i < len(base64Str):
        result += base64Str[i:i + 64] + "\n"
        i += 64
    return result
