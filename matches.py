from datetime import date

# FIFA World Cup 2026 confirmed group stage schedule
# All times UTC. Update as official schedule releases.
WC2026_MATCHES = [
    {"id":"m01","home":"MEXICO","away":"SOUTH AFRICA","date":"2026-06-11","time":"20:00 UTC"},
    {"id":"m02","home":"KOREA REPUBLIC","away":"CZECHIA","date":"2026-06-12","time":"03:00 UTC"},
    {"id":"m03","home":"CANADA","away":"BOSNIA AND HERZEGOVINA","date":"2026-06-12","time":"20:00 UTC"},
    {"id":"m04","home":"UNITED STATES","away":"PARAGUAY","date":"2026-06-13","time":"02:00 UTC"},
    {"id":"m05","home":"QATAR","away":"SWITZERLAND","date":"2026-06-13","time":"20:00 UTC"},
    {"id":"m06","home":"BRAZIL","away":"MOROCCO","date":"2026-06-13","time":"23:00 UTC"},
    {"id":"m07","home":"HAITI","away":"SCOTLAND","date":"2026-06-14","time":"02:00 UTC"},
    {"id":"m08","home":"AUSTRALIA","away":"TURKIYE","date":"2026-06-14","time":"05:00 UTC"},
    {"id":"m09","home":"GERMANY","away":"CURACAO","date":"2026-06-14","time":"18:00 UTC"},
    {"id":"m10","home":"NETHERLANDS","away":"JAPAN","date":"2026-06-14","time":"21:00 UTC"},
    {"id":"m11","home":"COTE D'IVOIRE","away":"ECUADOR","date":"2026-06-15","time":"00:00 UTC"},
    {"id":"m12","home":"SWEDEN","away":"TUNISIA","date":"2026-06-15","time":"03:00 UTC"},
    {"id":"m13","home":"SPAIN","away":"CABO VERDE","date":"2026-06-15","time":"17:00 UTC"},
    {"id":"m14","home":"BELGIUM","away":"EGYPT","date":"2026-06-15","time":"20:00 UTC"},
    {"id":"m15","home":"SAUDI ARABIA","away":"URUGUAY","date":"2026-06-15","time":"23:00 UTC"},
    {"id":"m16","home":"IRAN","away":"NEW ZEALAND","date":"2026-06-16","time":"02:00 UTC"},
    {"id":"m17","home":"FRANCE","away":"SENEGAL","date":"2026-06-16","time":"20:00 UTC"},
    {"id":"m18","home":"IRAQ","away":"NORWAY","date":"2026-06-16","time":"23:00 UTC"},
    {"id":"m19","home":"ARGENTINA","away":"ALGERIA","date":"2026-06-17","time":"02:00 UTC"},
    {"id":"m20","home":"AUSTRIA","away":"JORDAN","date":"2026-06-17","time":"05:00 UTC"},
    {"id":"m21","home":"PORTUGAL","away":"CONGO DR","date":"2026-06-17","time":"18:00 UTC"},
    {"id":"m22","home":"ENGLAND","away":"CROATIA","date":"2026-06-17","time":"21:00 UTC"},
    {"id":"m23","home":"GHANA","away":"PANAMA","date":"2026-06-18","time":"00:00 UTC"},
    {"id":"m24","home":"UZBEKISTAN","away":"COLOMBIA","date":"2026-06-18","time":"03:00 UTC"},
    {"id":"m25","home":"CZECHIA","away":"SOUTH AFRICA","date":"2026-06-18","time":"17:00 UTC"},
    {"id":"m26","home":"SWITZERLAND","away":"BOSNIA AND HERZEGOVINA","date":"2026-06-18","time":"20:00 UTC"},
    {"id":"m27","home":"CANADA","away":"QATAR","date":"2026-06-18","time":"23:00 UTC"},
    {"id":"m28","home":"MEXICO","away":"KOREA REPUBLIC","date":"2026-06-19","time":"02:00 UTC"},
    {"id":"m29","home":"USA","away":"AUSTRIA","date":"2026-06-19","time":"20:00 UTC"},
    {"id":"m30","home":"SCOTLAND","away":"MOROCCO","date":"2026-06-19","time":"23:00 UTC"},
    {"id":"m31","home":"BRAZIL","away":"HAITI","date":"2026-06-20","time":"01:30 UTC"},
    {"id":"m32","home":"TURKIYE","away":"PARAGUAY","date":"2026-06-20","time":"04:00 UTC"},
    {"id":"m33","home":"NETHERLANDS","away":"SWEDEN","date":"2026-06-20","time":"18:00 UTC"},
    {"id":"m34","home":"GERMANY","away":"COTE D'IVOIRE","date":"2026-06-20","time":"21:00 UTC"},
    {"id":"m35","home":"ECUADOR","away":"CURACAO","date":"2026-06-21","time":"01:00 UTC"},
    {"id":"m36","home":"TUNISIA","away":"JAPAN","date":"2026-06-21","time":"05:00 UTC"},

]

def get_todays_matches():
    today = str(date.today())
    return [m for m in WC2026_MATCHES if m["date"] == today]

def get_match_by_id(match_id):
    return next((m for m in WC2026_MATCHES if m["id"] == match_id), None)

def add_custom_match(match_id, home, away, match_date, time_utc):
    """Admin can add custom matches via bot command"""
    # Avoid duplicates
    if not any(m["id"] == match_id for m in WC2026_MATCHES):
        WC2026_MATCHES.append({
            "id": match_id, "home": home, "away": away,
            "date": match_date, "time": time_utc
        })