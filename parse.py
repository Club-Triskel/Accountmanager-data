import os
import sys
import psycopg2
import csv
import time
import pyotp


import vrchatapi
from vrchatapi.api import authentication_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.rest import ApiException

from http.cookiejar import LWPCookieJar

csv_file = 'triskel.csv'

cookie_file = 'cookies.txt'

configuration = vrchatapi.Configuration(
    username=os.environ['VRCHAT_USERNAME'],
    password=os.environ['VRCHAT_PASSWORD'],
)

vrchatUserAgent = "ClubTriskel/1.0 mralexh123@gmail.com"


def save_cookies(client: vrchatapi.ApiClient, filename: str):
    cookie_jar = LWPCookieJar(filename=filename)
    for cookie in client.rest_client.cookie_jar:
        cookie_jar.set_cookie(cookie)
    cookie_jar.save()


def load_cookies(client: vrchatapi.ApiClient, filename: str):
    cookie_jar = LWPCookieJar(filename=filename)
    try:
        cookie_jar.load()
    except FileNotFoundError:
        cookie_jar.save()
        return
    for cookie in cookie_jar:
        client.rest_client.cookie_jar.set_cookie(cookie)


def parse_csv(file_name):
    with open(file_name, newline='', encoding='utf-8') as csvfile:
        csvreader = csv.reader(csvfile)
        header = next(csvreader)
        parsed_data = []
        for row in csvreader:
            # Ensure that the row length matches the header length
            if len(row) != len(header):
                # If the row is shorter, pad it with empty strings
                row.extend([''] * (len(header) - len(row)))
                # If the row is longer, trim it to match the header
                row = row[:len(header)]
            user_data = {header[i]: row[i] for i in range(len(header))}
            parsed_data.append(user_data)
    return header, parsed_data


def get_vrc_username(VRCUrl):
    print(f"Getting username from {VRCUrl}")
    userID = VRCUrl.split('/')[-1]
    with vrchatapi.ApiClient(configuration) as api_client:
        api_client.user_agent = vrchatUserAgent
        load_cookies(api_client, cookie_file)

        api_instance = vrchatapi.UsersApi(api_client)
        try:
            api_response = api_instance.get_user(userID)
            print(api_response.display_name)
            time.sleep(0.5)  # Avoid rate limiting
            return api_response.display_name
        except ApiException as e:
            print("Exception when calling UsersApi->get_user: %s\n" % e)
            sys.exit()


def get2FaCode():
    totp = pyotp.TOTP(os.environ['VRCHAT2FA_SECRET'])
    return totp.now()


def authenticate_VRC():
    with vrchatapi.ApiClient(configuration) as api_client:
        api_client.user_agent = vrchatUserAgent
        load_cookies(api_client, cookie_file)

        auth_api = authentication_api.AuthenticationApi(api_client)
        try:
            current_user = auth_api.get_current_user()
        except UnauthorizedException as e:
            if "2 Factor Authentication" in e.reason:
                try:
                    auth_api.verify2_fa(two_factor_auth_code=TwoFactorAuthCode(get2FaCode()))
                    save_cookies(api_client, cookie_file)
                except ApiException as e:
                    print("Exception when calling AuthenticationApi->verify2_fa: %s\n" % e)
                    sys.exit()
                current_user = auth_api.get_current_user()
            else:
                raise e
        print("Logged in as:", current_user.display_name)


def write_to_csv(new_data, header):
    with open(csv_file, 'w', newline='', encoding='utf-8') as csvfile:  # Use 'w' to overwrite
        writer = csv.DictWriter(csvfile, fieldnames=header)
        writer.writeheader()  # Ensure the header is written
        for entry in new_data:
            writer.writerow(entry)


def Start():
    authenticate_VRC()

    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    cur.execute("SELECT * FROM userdb")
    rows = cur.fetchall()

    urlList = []
    DBDiscordID = []
    for row in rows:
        urlList.append(row[1])
        DBDiscordID.append(row[0])

    header, parsed_data = parse_csv(csv_file)
    csvList = []
    csvDiscordID = []
    for row in parsed_data:
        csvList.append(row['username'])
        csvDiscordID.append(row['discord id'])

    new_csv_data = parsed_data[:]  # Create a copy of the CSV data to update

    # Check if each Discord ID from the database is already in the CSV
    for discord_id, url in zip(DBDiscordID, urlList):
        if discord_id not in csvDiscordID:
            print(f"Discord ID {discord_id} not in CSV, fetching VRChat username...")
            vrc_username = get_vrc_username(url)

            # Check if the fetched VRChat username is already in the CSV
            if vrc_username in csvList:
                print(f"VRChat username {vrc_username} exists in the CSV but with a different Discord ID, updating Discord ID...")
                # Update the existing CSV entry for the username with the new Discord ID
                for entry in new_csv_data:
                    if entry['username'] == vrc_username:
                        entry['discord id'] = discord_id  # Update the Discord ID
                        break
            else:
                # Add the new user with the Discord ID and ID Verified role
                print(f"Adding {vrc_username} to the CSV database")
                new_entry = {col: False for col in header}  # Initialize all columns with False
                new_entry['username'] = vrc_username
                new_entry['discord id'] = discord_id
                new_entry['ID Verified'] = True
                new_csv_data.append(new_entry)

    # Write the updated CSV data back to the file
    write_to_csv(new_csv_data, header)

    cur.close()
    conn.close()


if __name__ == '__main__':
    Start()
