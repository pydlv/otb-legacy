import pyotp
import base64
import sys
import time
import requests
import json
import mycolors
import trading
from log import log 

class AuthHandler:
    def __init__(self, auth_secret):
        """
            This class will verify and handle the Authenticator
        """
        ok = self.verify_auth_secret(auth_secret)
        if ok != False or ok != None:
            self.authenticator = ok
        else:
            log(f"Failed to verify authenticator exiting", mycolors.FAIL)
            sys.exit(0)

    def verify_auth_secret(self, auth_secret):
        """
        This function is only to make sure the secret it correct
        """
        try:
            totp = pyotp.TOTP(auth_secret)
            code = totp.now()
        except ValueError:
            return False
        except Exception as e:
            print("error for verify auth", e)
            return False

        return totp


    def verify_request(self, req_session:requests.Session, user_Id, metadata_challengeId):
        """
        This is a handler function for verifying the 2fa
        """
        while True:
            xsrf = trading.get_xsrf()
            req_session.headers.update({"X-CSRF-TOKEN": xsrf})

            request = req_session.post("https://twostepverification.roblox.com/v1/users/" + user_Id + "/challenges/authenticator/verify", headers=req_session.headers, json={
                "actionType": "Generic",
                "challengeId": metadata_challengeId,
                "code": self.authenticator.now()
            })

            
            if "errors" in request.json():
                if request.status_code == 429:
                    print("Waiting 75 seconds for 2fa ratelimit", request.text)
                    time.sleep(75)
                    continue
                
                print("2fa error, waiting 120 seconds")
                print(request.json(), "FOR USER:", user_Id)
                time.sleep(120)
                #input(request.json()["errors"][0]["message"])
                return False
            try:
                return request.json()["verificationToken"]
            except:
                print("error returning verification token", request.text, request.status_code)
                continue

    def continue_request(self, request_session:requests.Session, challengeId, verification_token, metadata_challengeId):
        """
        Another Handler function that continues the request
        """
        response = request_session.post("https://apis.roblox.com/challenge/v1/continue", headers=request_session.headers, json={
            "challengeId": challengeId,
            "challengeMetadata": json.dumps({
                "rememberDevice": True,
                "actionType": "Generic",
                "verificationToken": verification_token,
                "challengeId": metadata_challengeId
            }),
            "challengeType": "twostepverification"
        })

        log(f"continue auth response: {response.text}", mycolors.WARNING, no_print=True)


    def validate_2fa(self, response, request_session):
        """
        This function takes a 401 error response and then returns the 2fa response if there is one
        """
        
        challengeid = response.headers["rblx-challenge-id"]
        metadata = json.loads(base64.b64decode(response.headers["rblx-challenge-metadata"]))
        try:
            metadata_challengeid = metadata["challengeId"]
        except Exception as e:
            print("couldnt get meta data challengeid from", metadata, "scraping from", response.headers, "for meta data", response.url)
            return False
        try:
            senderid = metadata["userId"]
        except Exception as e:
            print("couldnt get userid from", metadata, "scraping from", response.headers, "for meta data", response.url)
            return False

        # send the totp verify request to roblox
        verification_token = self.verify_request(request_session, senderid, metadata_challengeid)
        # send the continue request
        self.continue_request(request_session, challengeid, verification_token, metadata_challengeid)

        # add verification to headers
        return{
            'rblx-challenge-id': challengeid,
            'rblx-challenge-metadata': base64.b64encode(json.dumps({
                "rememberdevice": True,
                "actiontype": "generic",
                "verificationtoken": verification_token,
                "challengeid": metadata_challengeid
            }).encode()).decode(),
            'rblx-challenge-type': "twostepverification"
        }



