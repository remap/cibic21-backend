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

dynamoDbResource = boto3.resource('dynamodb')
sesClient = boto3.client('ses')

def lambda_handler(event, context):
    fromEmail = os.environ['ENV_VAR_FROM_EMAIL']
    toEmail = os.environ['ENV_VAR_TO_EMAIL']
    demographicSurveyId = os.environ['ENV_VAR_DEMOGRAPHIC_SURVEY_ID']
    journalsTable = dynamoDbResource.Table(CibicResources.DynamoDB.JournalingRequests)
    surveysTable = dynamoDbResource.Table(CibicResources.DynamoDB.RawSurveyResponses)

    try:
        #conn = psycopg2.connect(host=pgServer, database=pgDbName,
        #                        user=pgUsername, password=pgPassword)
        #cur = conn.cursor()
        #conn.commit()
        #cur.close()

        journalItems = journalsTable.scan(
          FilterExpression = Attr('type').eq('reflection') &
                             Attr('processed').eq(True)
        )['Items']
        print('Processing ' + str(len(journalItems)) + ' journal entries.')
        rows = []
        expectedPrompts = [
          'Rate your commute satisfaction:',
          'Select all the characteristics of your ride:',
          'Describe your ride with one word or short phrase:',
          'What color best expresses how you feel about your last CiBiC ride?'
        ]
        expectedSatisfactionOptions = [ 'Terrible', 'Bad', 'Okay', 'Good', 'Great' ]
        expectedColorOptions = [ 'blue', 'yellow', 'magenta', 'light blue', 'green', 'pink' ]

        surveyItems = surveysTable.scan(
          FilterExpression = Attr('surveyId').eq(demographicSurveyId)
        )['Items']
        # Replace each 'body' by decoding the JSON.
        for surveyItem in surveyItems:
            surveyItem['body'] = json.loads(surveyItem.get('body', "{}"))

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        for journalItem in journalItems:
            try:
                body = json.loads(journalItem['body'])
            except:
                continue

            answers = body.get('answers')
            journal = body.get('journal')
            if body.get('userId') == None or body.get('role') == None or answers == None or journal == None:
                continue
            if len(body['userId']) < 10:
                # Assume that a short user ID is for testing.
                continue

            userId = body['userId']
            role = body['role']

            # Pandas wants us to strip the time zone from the datetime.
            timestamp = datetime.fromisoformat(journalItem['timestamp']).replace(tzinfo=None)
            if timestamp < datetime.fromisoformat('2022-08-01T00:00:00'):
                # Older journal entries have a different format.
                continue

            # Fetch the latest ride before timestamp for the userId and role.
            sql = """
SELECT pod, "podName", flow, "flowName", "rideId"
  FROM {0}
  WHERE "userId" = '{1}' AND role = '{2}' AND "startTime" <= '{3}'
  ORDER BY "startTime" DESC
  LIMIT 1;
            """.format(CibicResources.Postgres.Rides, userId, role,
                       timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"))
            cur = conn.cursor()
            cur.execute(sql)

            pod = None
            podName = None
            flow = None
            flowName = None
            rideId = None

            # There should only be one result, so use fetchone.
            ride = cur.fetchone()
            if ride != None:
                pod = ride[0]
                podName = ride[1]
                flow = ride[2]
                flowName = ride[3]
                rideId = ride[4]

            conn.commit()
            cur.close()

            demographics = getDemographics(surveyItems, userId, role)

            row = [userId, role, timestamp, pod, podName, flow, flowName, rideId,
                   demographics.get('gender'), demographics.get('race'),
                   demographics.get('age'), demographics.get('income')]
                   
            for i in range(len(expectedPrompts)):
                if i >= len(answers) or i >= len(journal):
                    # The journal doesn't have enough responses.
                    row.append(None)
                    continue

                prompt = journal[i]['prompt']['en']
                if prompt != expectedPrompts[i]:
                    # The journal question has changed.
                    print('caught exception: For prompt #' + str(i) + ' expected "' +
                          expectedPrompts[i] + '", got "' + prompt + '"')
                    row.append("")
                    continue

                answer = answers[i]
                if answer == None or answer == '':
                    answer = None
                elif prompt == 'Rate your commute satisfaction:':
                    answerIndex = int(answer)
                    answerText = journal[i]['options'][answerIndex]['label']['en']
                    expectedAnswerText = expectedSatisfactionOptions[answerIndex]
                    if answerText != expectedAnswerText:
                        # The prompt at the index for this answer doesn't match the expected prompt.
                        print('caught exception: For prompt #' + str(i) + ', answer #' + str(answerIndex) +
                              ' expected "' + expectedAnswerText + '", got "' + answerText + '"')
                        answer = None
                elif prompt == 'Select all the characteristics of your ride:':
                    formattedAnswer = ''
                    for item in answer:
                        if formattedAnswer != '':
                            formattedAnswer += ', '
                        formattedAnswer += item.get('en', '')

                    answer = formattedAnswer
                elif prompt == 'What color best expresses how you feel about your last CiBiC ride?':
                    answerIndex = int(answer)
                    answerText = journal[i]['options'][answerIndex]
                    expectedAnswerText = expectedColorOptions[answerIndex]
                    if answerText != expectedAnswerText:
                        # The prompt at the index for this answer doesn't match the expected prompt.
                        print('caught exception: For prompt #' + str(i) + ', answer #' + str(answerIndex) +
                              ' expected "' + expectedAnswerText + '", got "' + answerText + '"')
                        answer = None

                row.append(answer)

            rows.append(row)

        headers = [] + expectedPrompts
        # Show the satisfaction options numbers in the header
        for i in range(len(expectedSatisfactionOptions)):
            headers[0] += (', ' if i > 0 else ' ') + str(i) + ' = ' + expectedSatisfactionOptions[i]
        headers[3] = 'Color Wheel (for interpretive cartography purposes)'
        # Show the color options numbers in the header
        for i in range(len(expectedColorOptions)):
            headers[3] += (', ' if i > 0 else ' ') + str(i) + ' = ' + expectedColorOptions[i]

        frame1 = pd.DataFrame(
            rows,
            columns=(['User ID', 'Role', 'Date (UTC)', 'Pod ID', 'Pod Name',
                      'Flow ID', 'Flow Name', 'Ride ID', 'Gender', 'Race',
                      'Age', 'Household Income'] + headers))
        #frame2 = pd.DataFrame([[1, 2], [3, 4]], columns=['col 1', 'col 2'])

        with io.BytesIO() as output:
            with pd.ExcelWriter(output) as writer:
                frame1.to_excel(writer, sheet_name='Daily Journals Report', index=False)
                #frame2.to_excel(writer, sheet_name='Monthly Survey Report', index=False)
            excel = output.getvalue()
        print('Excel output file size ' + str(len(excel)))
        ## TODO: When done testing, remove Lambda permissions to S3.
        #debug_s3.put_object(Bucket=CibicResources.S3Bucket.JournalingImages,
        #                    Key='CiBiC_Data_Report.xlsx', Body=excel)
        emailAttachment(fromEmail, toEmail,
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'CiBiC_Data_Report.xlsx', excel)

        return lambdaReply(200, {})
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

# Question IDs are obtained from https://api.surveymonkey.net/v3/surveys/{surveyId}/details .
genderQuestionId = "62792474"
genderAnswers = {
    "518764756": "Female",
    "518764757": "Male",
    "518764758": "Transgender Female",
    "518764759": "Transgender Male",
    "518764760": "Genderqueer",
    "518764761": "Nonbinary",
    "518764762": "Prefer not to state"
}
raceQuestionId = "62792754"
raceAnswers = {
    "518766842": "Asian",
    "518766843": "Black or African American",
    "518766844": "Hispanic or Latino",
    "518766845": "Middle Eastern or North African",
    "518766846": "Multiracial or Multiethnic",
    "518766847": "Native American or Alaska Native",
    "518766848": "Native Hawaiian or other Pacific Islander",
    "518766849": "White",
    "518766850": "other",
}
ageQuestionId = "83765566"
incomeQuestionId = "62792820"
incomeAnswers = {
    "518767237": "Less than $20000",
    "518767238": "$20000 to $34999",
    "518767239": "$35000 to $49999",
    "518767240": "$50000 to $74999",
    "518767241": "$75000 to $99999",
    "518767242": "$100000 to $149999",
    "518767243": "$150000 or More"
}

def getDemographics(surveyItems, userId, role):
    """
    Find the item in surveyItems matching the userId and role. Return an object
    with found values.
    """

    result = {}
    for item in surveyItems:
        if item.get('userId') == userId and item.get('role') == role:
            # Convert list of { 'id': x, 'answers': y} into a dict.
            answers = {}
            for answer in item['body'].get('pages', [{}])[0].get('questions', []):
                if 'id' in answer and 'answers' in answer:
                    answers[answer['id']] = answer['answers']

            if genderQuestionId in answers:
                if 'text' in answers[genderQuestionId][0]:
                    result['gender'] = answers[genderQuestionId][0]['text']
                else:
                    answerId = answers[genderQuestionId][0].get('choice_id')
                    if answerId in genderAnswers:
                        result['gender'] = genderAnswers[answerId]
                    else:
                        print('caught exception: Unrecognized gender answer ID ' + answerId +
                          ' in demographic survey for userId ' + userId + ', role ' + role)
            else:
                print('caught exception: Gender question ID ' + genderQuestionId +
                  ' not in demographic survey for userId ' + userId + ', role ' + role)

            if raceQuestionId in answers:
                answerId = answers[raceQuestionId][0].get('choice_id')
                if answerId in raceAnswers:
                    if raceAnswers[answerId] == 'other':
                        result['race'] = answers[raceQuestionId][1].get('text')
                    else:
                        result['race'] = raceAnswers[answerId]
                else:
                    print('caught exception: Unrecognized race answer ID ' + answerId +
                      ' in demographic survey for userId ' + userId + ', role ' + role)
            else:
                print('caught exception: Race question ID ' + raceQuestionId +
                  ' not in demographic survey for userId ' + userId + ', role ' + role)

            if ageQuestionId in answers:
                ageText = answers[ageQuestionId][0].get('text')
                try:
                    result['age'] = int(ageText)
                except ValueError:
                    result['age'] = ageText
            else:
                print('caught exception: Age question ID ' + ageQuestionId +
                  ' not in demographic survey for userId ' + userId + ', role ' + role)

            if incomeQuestionId in answers:
                answerId = answers[incomeQuestionId][0].get('choice_id')
                if answerId in incomeAnswers:
                    result['income'] = incomeAnswers[answerId]
                else:
                    print('caught exception: Unrecognized income answer ID ' + answerId +
                      ' in demographic survey for userId ' + userId + ', role ' + role)
            else:
                print('caught exception: Income question ID ' + genderQuestionId +
                  ' not in demographic survey for userId ' + userId + ', role ' + role)

            break

    return result

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
