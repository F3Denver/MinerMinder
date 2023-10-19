import mysql.connector
import os
from slack_sdk import WebClient
from operator import itemgetter
from itertools import groupby
from datetime import datetime

def GetBlockHeader(message):
	return {
		"type": "header",
		"text": {
			"type": "plain_text",
			"text": message
		}
	}

def GetBlockContext(message):
	return {
		"type": "context",
		"elements": [
			{
				"type": "plain_text",
				"text": message
			}
		]
	}

def GetBlockSection(message):
	return {
		"type": "section",
		"text": {
			"type": "mrkdwn",
			"text": message
		}
	}

def checkForMissingBackblasts(request):

	slackWorkspacesInputs = "Denver,TCT7SH4JC,C04R36F5YGJ,1,75,2;Denver2,TCT7SH4JC,,1,75,3" #os.getenv("slackWorkspacesInputs")
	slackTokens = "xoxb-435264582624-4829806996614-2HKBw7Zy0FdciIt02iLwtcWu;xoxb-435264582624-4829806996614-2HKBw7Zy0FdciIt02iLwtcWu" #os.getenv("slackToken")

	slackWorkspacesInputs = slackWorkspacesInputs.split(";")
	slackTokens = slackTokens.split(";")

	mydb = mysql.connector.connect(
		host="f3stlouis.cac36jsyb5ss.us-east-2.rds.amazonaws.com",#os.getenv("paxMinerSqlServer"),
		user="paxminer", #os.getenv("paxMinerUsername"),
		password="AyeF3read0nly!", #os.getenv("paxMinerPassword"),
		database="f3denver" #os.getenv("paxMinerDatabase")
	)

	indexQ = 4
	indexAO = 5
	indexSiteQ = 6

	for i, slackWorkspaceInputs in enumerate(slackWorkspacesInputs):
		inputs = slackWorkspaceInputs.split(",")
		workspaceName = inputs[0]
		workspaceId = inputs[1]
		logChannelId = inputs[2]
		notificationGracePeriodDays = inputs[3]
		notificationCutoffDays = inputs[4]
		channelTriggerDay = int(inputs[5]) # The day of the week AO and Site Q alerts go out. Monday is 0.
		slackToken = slackTokens[i]

		print("Starting " + workspaceName)

		client = WebClient(token=slackToken)

		cursor = mydb.cursor()
		cursor.execute("""
			SELECT
				qmbd.event_date AS BD_Date,
				qmbd.event_time AS BD_TIME,
				LEFT(qmbd.event_day_of_week, 3) AS BD_DAY,
				qmbd.event_type AS BD_TYPE,
				COALESCE (qmbd.q_pax_id, "") AS Q,
				qmbd.ao_channel_id AS AO,
				aos.site_q_user_id  AS SiteQ
			FROM
				(
				SELECT
					*
				FROM
					f3stcharles.qsignups_master qm
				WHERE
					NOT EXISTS
					(
					SELECT
						*
					FROM
						f3denver.beatdowns bd
					WHERE
						qm.ao_channel_id = bd.ao_id
						AND qm.event_date = bd.bd_date )
					AND qm.team_id = '""" + workspaceId + """'
					AND qm.event_date > (NOW() - INTERVAL """ + str(notificationCutoffDays) + """ DAY )
					AND qm.event_date < (NOW() - INTERVAL """ + str(notificationGracePeriodDays) + """ DAY)
				ORDER BY
					qm.event_date,
					qm.event_time) qmbd
			LEFT JOIN
			(
				SELECT
					*
				FROM
					f3denver.aos) aos
			ON
				qmbd.ao_channel_id = aos.channel_id
			ORDER BY
				qmbd.event_date,
				qmbd.event_time
		""")
		data = cursor.fetchall()

		print("Missing backblasts found: "+ str(len(data)))
		
		if logChannelId != "" and not logChannelId.isspace():
			client.chat_postMessage(channel=logChannelId, text="Miner Minder: There are " + str(len(data)) + " missing backblasts as of today (checked between " + str(notificationGracePeriodDays) + " and " + str(notificationCutoffDays) + " days ago).")
		
		if len(data) == 0:
			continue

		# Daily Q Reminder
		dataSorted = [item for item in data if item[indexQ] != '']
		dataSorted.sort(key=itemgetter(indexQ))
		qs = []
		for k,g in groupby(dataSorted, itemgetter(indexQ)):
			qs.append(list(g))

		for q in qs:
			message = []
			message.append(GetBlockHeader("MinerMinder Alert!"))
			message.append(GetBlockContext("It looks like you forgot to post the following backblast(s). :grimacing:"))
			qId = q[0][indexQ]
			
			for missingBB in q:
				message.append(GetBlockSection("A " + missingBB[3] + " at <#" + missingBB[indexAO] + "> on " + missingBB[0].strftime("%A") + " " + missingBB[0].strftime("%m/%d/%y") + " at " + missingBB[1]))

			client.chat_postMessage(channel="C04R36F5YGJ", text="Missing Backblast!!! :grimacing:", blocks=message) # channel=qId

		# The rest of the reminders are only weekly
		if datetime.today().weekday() != channelTriggerDay:
			continue

		# Site Q Reminder
		dataSorted = [item for item in data if item[indexSiteQ] is not None]
		dataSorted.sort(key=itemgetter(indexSiteQ))
		siteQs = []
		for k,g in groupby(dataSorted, itemgetter(indexSiteQ)):
			siteQs.append(list(g))

		for siteQ in siteQs:
			message = []
			message.append(GetBlockHeader("MinerMinder Alert!"))
			message.append(GetBlockContext("It looks like there are backblasts missing at the site(s) you lead. :warning:"))
			siteQId = siteQ[0][indexSiteQ]
			
			for missingBB in siteQ:
				messagePart = "A " + missingBB[3] + " at <#" + missingBB[indexAO] + "> on " + missingBB[0].strftime("%A") + " " + missingBB[0].strftime("%m/%d/%y") + " at " + missingBB[1]
				if (missingBB[indexQ] != ''):
					messagePart = messagePart + (" (<@" + missingBB[indexQ] + "> was Q)")
				message.append(GetBlockSection(messagePart))

			client.chat_postMessage(channel="C04R36F5YGJ", text="Missing Backblasts at your AO! :warning:", blocks=message) # channel=siteQId

		# Channel Reminder
		data.sort(key=itemgetter(indexAO))
		aos = []
		for k,g in groupby(data, itemgetter(indexAO)):
			aos.append(list(g))

		for ao in aos:
			message = []
			message.append(GetBlockHeader("MinerMinder Alert!"))
			message.append(GetBlockContext("It looks like there are backblasts missing at this AO. :exploding_head:"))
			aoId = ao[0][indexAO]
			
			for missingBB in ao:
				messagePart = "A " + missingBB[3] + " on " + missingBB[0].strftime("%A") + " " + missingBB[0].strftime("%m/%d/%y") + " at " + missingBB[1]
				if (missingBB[indexQ] != ''):
					messagePart = messagePart + (" (<@" + missingBB[indexQ] + "> was Q)")
				message.append(GetBlockSection(messagePart))

			client.chat_postMessage(channel="C04R36F5YGJ", text="Missing Backblasts at this AO! :exploding_head:", blocks=message) # channel=aoId
			
	return 'OK'

checkForMissingBackblasts("")