# randomizers.py
import random
from datetime import datetime

def random_bait_subject(account_type="General", username=""):
    templates = [
        "{year} {asset} Recovery Seed – Urgent Backup",
        "Emergency {asset} Access Codes – {month} {year}",
        "CONFIDENTIAL: {asset} Root Credentials – {username}",
        "{asset} Wallet Backup – Do Not Delete ({random_id})",
        "Account Recovery: {asset} Keys – Last Chance {year}",
        "Internal {asset} Admin Export – {month_abbr} {day}",
        "{asset} Seed Phrase Archive – {random_word} Version",
    ]
    
    assets = ["Bitcoin", "Ethereum", "Google", "AWS", "Microsoft", "VPN", "Password Manager", "Crypto"]
    random_words = ["Final", "Secure", "Encrypted", "Legacy", "Master", "Hidden", "Private"]
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    month_abbr = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    
    year = str(datetime.now().year)
    month = random.choice(months)
    month_abbr_choice = random.choice(month_abbr)
    day = str(random.randint(1, 28))
    random_id = f"{random.randint(1000,9999)}-{random.randint(10,99)}"
    random_word = random.choice(random_words)
    asset = random.choice(assets) if account_type == "General" else account_type
    
    base = random.choice(templates)
    subject = base.format(
        year=year,
        asset=asset,
        month=month,
        month_abbr=month_abbr_choice,
        day=day,
        username=username or "Admin",
        random_id=random_id,
        random_word=random_word
    )
    
    if random.random() < 0.3:
        subject += random.choice([" 🔒", " ⚠️", " 💾", " 📂"])
    
    return subject

def random_decoy_filename(account_type="General", extension="html"):
    prefixes = ["Backup_", "Export_", "Archive_", "Recovery_", "Credentials_", "Secure_", ""]
    suffixes = ["_Final", "_v2", "_2026", "_Encrypted", "_Private", ""]
    ids = [f"{random.randint(1000,9999)}", f"{random.randint(10,99)}-{random.randint(100,999)}", ""]
    
    base = f"{random.choice(prefixes)}{account_type}_{random.randint(2018,2026)}{random.choice(suffixes)}"
    if random_id := random.choice(ids):
        base += f"_{random_id}"
    
    return f"{base}.{extension}"