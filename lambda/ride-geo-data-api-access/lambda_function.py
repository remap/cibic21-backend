# This Lambda is for the ride GeoJSON access API. For /ride/get, query parameters
# is just 'rideId'. For /ride/query, query parameters are 'startTime' and 'endTime'
# (required) plus 'region', 'organization' and 'requireFlow' (optional).
# Get the matching rides from the Rides Postgres table and combine with
# WaypointsRaw and RideFlowWaypoints. Retur the result in GeoJSON.

from common.cibic_common import *
import os
import psycopg2
from datetime import datetime
import urllib

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']

def lambda_handler(event, context):
    try:
        print (event)
        if event['requestContext']['resourcePath'] == '/ride/get':
            if 'rideId' in event['queryStringParameters']:
                rideId = event['queryStringParameters']['rideId']
                # fetch ride from postgres as GeJSON
                print('fetching ride {}...'.format(rideId))
                rideData = fetchRide(rideId)
                if rideData:
                    return lambdaReply(200, rideData)
                else:
                    print('no ride with id {} found'.format(rideId))
                    return lambdaReply(404, 'not found')

        if event['requestContext']['resourcePath'] == '/ride/query':
            if 'startTime' in event['queryStringParameters'] and 'endTime' in event['queryStringParameters']:
                startTime = parseDatetime(event['queryStringParameters']['startTime'])
                endTime = parseDatetime(event['queryStringParameters']['endTime'])

                if not startTime or not endTime:
                    return lambdaReply(420, 'bad format for startTime/endTime parameters')

                region = event['queryStringParameters'].get('region')
                organization = event['queryStringParameters'].get('organization')
                requireFlow = ('requireFlow' in event['queryStringParameters'])

                if 'idsOnly' in event['queryStringParameters']:
                    rides = queryRidesSimple(startTime, endTime, region, organization, requireFlow)
                else:
                    rides = queryRidesRich(startTime, endTime, region, organization, requireFlow)
                print('fetched {} rides'.format(len(rides)))
                return lambdaReply(200, rides)
            else:
                return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def fetchRide(rideId):
    sql = """
            SET TIME ZONE 'America/Los_Angeles';
            SELECT json_build_object(
                     'type', 'FeatureCollection',
                     'features', array_to_json(feature_list),
                     'properties', json_build_object(
                                     'rideId', rid,
                                     'startTime', start_time,
                                     'endTime', end_time,
                                     'userId', user_id,
                                     'role', role,
                                     'flow', flow,
                                     'flowName', flow_name,
                                     'flowIsToWork', flow_is_to_work,
                                     'commute', commute,
                                     'flowJoinPoints', flow_join_points_json,
                                     'flowLeavePoints', flow_leave_points_json,
                                     'pod', pod,
                                     'podName', pod_name,
                                     'podMember', pod_member_json,
                                     'inferredPod', inferred_pod,
                                     'inferredPodName', inferred_pod_name,
                                     'weather', weather_json,
                                     'region', region,
                                     'organization', organization,
                                     'flowPath', flow_path
                                   )
                   )
            FROM (SELECT array[json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(start_zone)::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(end_zone)::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', json_build_object(
                                              'type', 'LineString',
                                              'coordinates', array_to_json(ride_line)
                                            ))
                               ] AS feature_list,
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(flow_line)::json) AS flow_path,
                               rid, start_time, end_time, user_id, role, flow, flow_name, flow_is_to_work, commute,
                               flow_join_points_json, flow_leave_points_json, pod, pod_name, pod_member_json,
                               inferred_pod, inferred_pod_name, weather_json, region, organization
                  FROM (SELECT ride."startZone" AS start_zone,
                               ride."endZone" AS end_zone,
                               wp.ride_line,
                               flow_wp.flow_line,
                               ride."rideId" AS rid,
                               ride."startTime" AS start_time,
                               ride."endTime" AS end_time,
                               ride."userId" AS user_id,
                               ride."role" AS role,
                               ride."flow" AS flow,
                               ride."flowName" AS flow_name,
                               ride."flowIsToWork" AS flow_is_to_work,
                               ride."commute" AS commute,
                               ride."flowJoinPointsJson" AS flow_join_points_json,
                               ride."flowLeavePointsJson" AS flow_leave_points_json,
                               ride."pod" AS pod,
                               ride."podName" AS pod_name,
                               ride."podMemberJson" AS pod_member_json,
                               ride."inferredPod" AS inferred_pod,
                               ride."inferredPodName" AS inferred_pod_name,
                               ride."weatherJson" AS weather_json,
                               ride."region" AS region,
                               ride."organization" AS organization
                         FROM {0} AS ride
                         LEFT JOIN (SELECT "rideId",
                                       array_agg("pointJson" ORDER BY "idx") AS ride_line
                                    FROM {1}
                                    WHERE zone = 'main'
                                    GROUP BY "rideId") AS wp
                         ON ride."rideId" = wp."rideId"
                         LEFT JOIN (SELECT "rideId", ST_MakeLine(array_agg(coordinate::geometry ORDER BY "idx")) AS flow_line
                                    FROM {2}
                                    GROUP BY "rideId") AS flow_wp
                         ON ride."rideId" = flow_wp."rideId"
                         WHERE ride."rideId" = '{3}'
                       ) AS geo
                 ) AS feature_collection;
          """.format(CibicResources.Postgres.Rides, CibicResources.Postgres.WaypointsRaw,
                     CibicResources.Postgres.RideFlowWaypoints, rideId)
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                            user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    rideData = None
    results = cur.fetchall()
    if len(results):
        print('ride fetched {}'.format(results[0]))
        rideData = results[0][0]

    conn.commit()
    cur.close()

    return rideData

def parseDatetime(ss):
    try:
        return datetime.fromisoformat(urllib.parse.unquote(ss))
    except:
        return None

def queryRidesSimple(startTime, endTime, region, organization, requireFlow):
    """
    Get only the rideId where startTime is between startTime and endTime.
    If region is not None, restrict to the region.
    If organization is not None, restrict to the organization.
    if requireFlow is True, restrict to rides where the flow is not NULL.
    """
    extraWhere = ''
    if region != None:
        extraWhere += " AND ride.region = '{}'".format(region)
    if organization != None:
        extraWhere += " AND ride.organization = '{}'".format(organization)
    if requireFlow:
        extraWhere += " AND ride.flow IS NOT NULL"

    sql = """
            SELECT ride."rideId"
            FROM {0} as ride
            WHERE ride."startTime" BETWEEN '{1}' AND '{2}' {3}
          """.format(CibicResources.Postgres.Rides,
                     startTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
                     endTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"), extraWhere)
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                        user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    rides = []
    for r in cur.fetchall():
        rides.append(r[0])
    conn.commit()
    cur.close()

    return rides


def queryRidesRich(startTime, endTime, region, organization, requireFlow):
    """
    Get the full GeoJSON for the rides where startTime is between startTime and endTime.
    If region is not None, restrict to the region.
    If organization is not None, restrict to the organization.
    if requireFlow is True, restrict to rides where the flow is not NULL.
    """
    extraWhere = ''
    if region != None:
        extraWhere += " AND ride.region = '{}'".format(region)
    if organization != None:
        extraWhere += " AND ride.organization = '{}'".format(organization)
    if requireFlow:
        extraWhere += " AND ride.flow IS NOT NULL"

    sql = """
            SET TIME ZONE 'America/Los_Angeles';
            SELECT json_build_object(
                     'type', 'FeatureCollection',
                     'features', array_to_json(feature_list),
                     'properties', json_build_object(
                                     'rideId', rid,
                                     'startTime', start_time,
                                     'endTime', end_time,
                                     'userId', user_id,
                                     'displayName', display_name, 
                                     'role', role,
                                     'flow', flow,
                                     'flowName', flow_name,
                                     'flowIsToWork', flow_is_to_work,
                                     'commute', commute,
                                     'flowJoinPoints', flow_join_points_json,
                                     'flowLeavePoints', flow_leave_points_json,
                                     'pod', pod,
                                     'podName', pod_name,
                                     'podMember', pod_member_json,
                                     'inferredPod', inferred_pod,
                                     'inferredPodName', inferred_pod_name,
                                     'weather', weather_json,
                                     'region', region,
                                     'organization', organization,
                                     'flowPath', flow_path
                                   )
                   )
            FROM (SELECT array[json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(start_zone)::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(end_zone)::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', json_build_object(
                                              'type', 'LineString',
                                              'coordinates', array_to_json(ride_line)
                                            ))
                               ] AS feature_list,
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(flow_line)::json) AS flow_path,
                               rid, start_time, end_time, user_id, display_name, role, flow, flow_name, flow_is_to_work, commute,
                               flow_join_points_json, flow_leave_points_json, pod, pod_name, pod_member_json,
                               inferred_pod, inferred_pod_name, weather_json, region, organization
                  FROM (SELECT ride."startZone" AS start_zone,
                               ride."endZone" AS end_zone,
                               wp.ride_line,
                               flow_wp.flow_line,
                               ride."rideId" AS rid,
                               ride."startTime" AS start_time,
                               ride."endTime" AS end_time,
                               ride."userId" AS user_id,
                               users."displayName" as display_name, 
                               ride."role" AS role,
                               ride."flow" AS flow,
                               ride."flowName" AS flow_name,
                               ride."flowIsToWork" AS flow_is_to_work,
                               ride."commute" AS commute,
                               ride."flowJoinPointsJson" AS flow_join_points_json,
                               ride."flowLeavePointsJson" AS flow_leave_points_json,
                               ride."pod" AS pod,
                               ride."podName" AS pod_name,
                               ride."podMemberJson" AS pod_member_json,
                               ride."inferredPod" AS inferred_pod,
                               ride."inferredPodName" AS inferred_pod_name,
                               ride."weatherJson" AS weather_json,
                               ride."region" AS region,
                               ride."organization" AS organization
                         FROM {0} AS ride
                         LEFT JOIN (SELECT "rideId",
                                       array_agg("pointJson" ORDER BY "idx") AS ride_line
                                    FROM {1}
                                    WHERE zone = 'main'
                                    GROUP BY "rideId") AS wp
                         ON ride."rideId" = wp."rideId"
                         LEFT JOIN (SELECT "rideId", ST_MakeLine(array_agg(coordinate::geometry ORDER BY "idx")) AS flow_line
                                    FROM {2}
                                    GROUP BY "rideId") AS flow_wp
                         ON ride."rideId" = flow_wp."rideId"
                         LEFT JOIN (SELECT "userId", "displayName" from {6}) AS users
                         ON ride."userId" = users."userId"
                         WHERE ride."startTime" BETWEEN '{3}' AND '{4}' {5}
						             ORDER BY ride."startTime" DESC
                       ) AS geo
                 ) AS feature_collection;
          """.format(CibicResources.Postgres.Rides, CibicResources.Postgres.WaypointsRaw, CibicResources.Postgres.RideFlowWaypoints,
                    startTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
                    endTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"), extraWhere, CibicResources.Postgres.UserEnrollments)
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                            user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    rides = []
    for r in cur.fetchall():
        rides.append(r[0])
    conn.commit()
    cur.close()

    return rides
