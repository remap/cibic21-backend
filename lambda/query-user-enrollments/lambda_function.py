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
          SELECT "userId", "role", "active", "outwardFlowName", "outwardFlowId", "returnFlowName", "returnFlowId",
            "outwardPodName", "outwardPodId", "returnPodName", "returnPodId",
            "homeAddressText", "homeFullAddress", "homeZipCode", "homeCoordinate", "homeGeofenceRadius",
            "workAddressText", "workFullAddress", "workZipCode", "workCoordinate", "workGeofenceRadius"
          FROM {}
        """.format(CibicResources.Postgres.UserEnrollments)
        cur.execute(sql)

        enrollmentsResponse = []
        for enrollment in cur.fetchall():
            enrollmentsResponse.append({
              'userId': enrollment[0],
              'role': enrollment[1],
              'active': enrollment[2],
              'outwardFlowName': enrollment[3],
              'outwardFlowId': enrollment[4],
              'returnFlowName': enrollment[5],
              'returnFlowId': enrollment[6],
              'outwardPodName': enrollment[7],
              'outwardPodId': enrollment[8],
              'returnPodName': enrollment[9],
              'returnPodId': enrollment[10],
              'home': {
                'addressText': enrollment[11],
                'fullAddress': enrollment[12],
                'zipCode': enrollment[13],
                'coordinate': enrollment[14],
                'geofenceRadius': enrollment[15]
              },
              'work': {
                'addressText': enrollment[16],
                'fullAddress': enrollment[17],
                'zipCode': enrollment[18],
                'coordinate': enrollment[19],
                'geofenceRadius': enrollment[20]
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
