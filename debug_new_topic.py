import requests
from bs4 import BeautifulSoup
import re

def read_config():
    cookie = None
    try:
        with open(".config", "r") as f:
            for line in f:
                if "cookie=" in line:
                    cookie = line.split("=", 1)[1].strip()
    except:
        pass
    return cookie

cookie = read_config()
if not cookie:
    print("No cookie found in .config")
    exit()

headers = {
    "Cookie": f"MoodleSession={cookie}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

BASE = "https://paatshala.ictkerala.org"
COURSE_ID = "345"

# 1. Get Sesskey
print("Fetching course page to get sesskey...")
resp = requests.get(f"{BASE}/course/view.php?id={COURSE_ID}", headers=headers)
soup = BeautifulSoup(resp.text, "html.parser")
sesskey = ""
logout_link = soup.find("a", href=lambda h: h and "sesskey=" in h)
if logout_link:
    m = re.search(r"sesskey=([^&]+)", logout_link["href"])
    if m:
        sesskey = m.group(1)
print(f"Sesskey: {sesskey}")

# 2. Add Topic
print("Adding new topic...")
add_url = f"{BASE}/course/changenumsections.php"
params = {
    "courseid": COURSE_ID,
    "insertsection": 0,
    "sesskey": sesskey,
    "sectionreturn": 0,
    "numsections": 1
}
resp = requests.get(add_url, params=params, headers=headers)
print(f"Add status: {resp.status_code}")

# 3. Fetch Page with Edit Mode
print("Fetching page with edit=on...")
resp = requests.get(f"{BASE}/course/view.php?id={COURSE_ID}&edit=on", headers=headers)
soup = BeautifulSoup(resp.text, "html.parser")

# 4. Inspect Last Section
print(f"Page Title: {soup.title.string if soup.title else 'No Title'}")

sections = soup.find_all("li", class_="section main")
if not sections:
    print("Trying fallback selector 'li.section'...")
    sections = soup.find_all("li", class_="section")

if sections:
    last_section = sections[-1]
    print("\n--- Last Section HTML ---")
    print(last_section.prettify())
    
    # Try to extract ID
    db_id = ""
    inplace_span = last_section.find("span", class_="inplaceeditable", attrs={"data-itemtype": "sectionname"})
    if inplace_span:
        db_id = inplace_span.get("data-itemid")
        print(f"\nFound ID via span: {db_id}")
    
    if not db_id:
        edit_link = last_section.find("a", href=lambda h: h and "editsection.php?id=" in h and "&sr" in h and "delete" not in h)
        if edit_link:
            print(f"\nFound edit link: {edit_link['href']}")
            m = re.search(r"id=(\d+)", edit_link["href"])
            if m:
                db_id = m.group(1)
                print(f"Found ID via link: {db_id}")
    
    if not db_id:
        print("\nNO ID FOUND!")
else:
    print("No sections found!")
