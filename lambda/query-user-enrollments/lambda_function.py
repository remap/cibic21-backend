# This Lambda for the API to query the Posgres table and return user enrollments.

from common.cibic_common import *
import os
import psycopg2

pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        print('query-user-enrollments event data: ' + str(event))

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        cur = conn.cursor()

        sql = """
          SELECT "userId", role, active, "displayName", email,
            "consentedName", "consentedEmail", "consentedPhone", to_json("consentedTime"),
            "outwardFlowName", "outwardFlowId", "returnFlowName", "returnFlowId",
            "outwardPodName", "outwardPodId", "returnPodName", "returnPodId",
            "homeAddressText", "homeFullAddress", "homeZipCode", "homeCoordinate", "homeGeofenceRadius",
            "workAddressText", "workFullAddress", "workZipCode", "workCoordinate", "workGeofenceRadius",
            region, organization
          FROM {}
        """.format(CibicResources.Postgres.UserEnrollments)
        cur.execute(sql)

        enrollmentsResponse = []
        for enrollment in cur.fetchall():
            enrollmentsResponse.append({
              'region': enrollment[27],
              'organization': enrollment[28],
              'userId': enrollment[0],
              'role': enrollment[1],
              'active': enrollment[2],
              'displayName': enrollment[3],
              'email': enrollment[4],
              "consentedName": enrollment[5],
              "consentedEmail": enrollment[6],
              "consentedPhone": enrollment[7],
              "consentedTime": enrollment[8],
              'outwardFlowName': enrollment[9],
              'outwardFlowId': enrollment[10],
              'returnFlowName': enrollment[11],
              'returnFlowId': enrollment[12],
              'outwardPodName': enrollment[13],
              'outwardPodId': enrollment[14],
              'returnPodName': enrollment[15],
              'returnPodId': enrollment[16],
              'home': {
                'addressText': enrollment[17],
                'fullAddress': enrollment[18],
                'zipCode': enrollment[19],
                'coordinate': enrollment[20],
                'geofenceRadius': enrollment[21]
              },
              'work': {
                'addressText': enrollment[22],
                'fullAddress': enrollment[23],
                'zipCode': enrollment[24],
                'coordinate': enrollment[25],
                'geofenceRadius': enrollment[26]
              }
            })

        conn.commit()
        cur.close()

        print("Returning {} enrollments".format(len(enrollmentsResponse)))
        requestReply = lambdaReply(200, enrollmentsResponse)
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return requestReply
