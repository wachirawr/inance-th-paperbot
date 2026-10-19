คู่มือติดตั้ง Binance TH PaperBot — iPhone / iPad
=============================================
อัปเดต 19 ตุลาคม 2026

วัตถุประสงค์
- ดึงข้อมูล Bid/Ask และแท่งเทียนจาก Binance TH Public API ทุกประมาณ 60 วินาที
- สแกน 3 คู่เหรียญ BTCTHB, ETHTHB, SOLTHB
- ทดลองเทรดเฉพาะ BTC/THB ด้วยเงินจำลอง 100,000 บาท
- ตรรกะทดลอง: เส้นค่าเฉลี่ย SMA 9/21 ของแท่งเทียน 15 นาทีที่ปิดแล้ว
- จำลองการเข้าซื้อ 2,000 บาทต่อสัญญาณ, ค่าธรรมเนียมประมาณ 0.25% และ Slippage 0.05%
- Stop Loss 2%, Take Profit 4% จากราคาเข้าซื้อ (ค่าจำลอง)
- บันทึกฐานข้อมูล SQLite และส่ง Telegram เมื่อเริ่มระบบ/มีออเดอร์จำลอง/สรุปทุก 6 ชั่วโมง

ข้อสำคัญ
1. โปรแกรมไม่มีโค้ดส่งคำสั่งซื้อขายเงินจริง ไม่มี Binance API Key และรองรับ MODE=PAPER เท่านั้น
2. เป็นบอทตามกฎการซื้อขาย ยังไม่ได้เรียกบริการ AI วิเคราะห์ระหว่างรัน
3. ผล Paper Trading ไม่ใช่การันตีกำไร และราคาเข้าซื้อ/ค่าธรรมเนียมเป็นเพียงแบบจำลอง
4. ไม่ควรส่ง Telegram Token ให้บุคคลอื่นหรืออัปโหลดไฟล์ .env เข้า GitHub
5. หาก Binance TH ปฏิเสธ IP ของ VPS, อัตราเรียกข้อมูลเกินกำหนด หรือคู่เหรียญเปลี่ยน ต้องแก้ไขก่อนจึงจะใช้งานได้

แอป/บัญชีที่ใช้
- Safari บน iPad, แอป Files, GitHub (ฟรี), DigitalOcean (มีค่าใช้จ่าย), Telegram (ฟรี)
- Termius (ทางเลือก) เพื่อจัดการ SSH ผ่าน iPad
- Binance TH App เป็นทางเลือกสำหรับดูราคาจริง; การอ่าน Public API ไม่ต้องลงทะเบียนและไม่ต้องเติมเงิน

ขั้นตอน A: สร้าง Telegram Bot
1. เปิด Telegram และค้นหา @BotFather อย่างเป็นทางการ
2. ส่ง /newbot แล้วตั้งชื่อและ username ที่ลงท้ายด้วย bot
3. เก็บ token ในที่ปลอดภัย อย่าส่งลงแชตสาธารณะ
4. เปิดแชตกับบอทของคุณ กด Start และส่งคำว่า Hello

ขั้นตอน B: อัปโหลด Source Code จาก iPad ไป GitHub
1. ดาวน์โหลดไฟล์ ZIP จาก ChatGPT แล้วกดแตกไฟล์ในแอป Files
2. เปิด github.com ใน Safari, สมัครบัญชี, เปิด 2FA
3. กด New Repository ตั้งชื่อ binance-th-paperbot เลือก Public เฉพาะโค้ดที่ไม่มีความลับ
4. Add file > Upload files เลือก bot.py, install.sh, sample.env, test_bot.py, README_TH.txt
5. กด Commit changes และจดชื่อบัญชี GitHub กับชื่อ Repository
   ห้ามอัปโหลด .env ที่ใส่ TOKEN, *.db หรือข้อมูลส่วนตัว

ขั้นตอน C: สร้างเซิร์ฟเวอร์ DigitalOcean
1. สมัคร digitalocean.com เปิด 2FA และใส่วิธีชำระเงิน
2. Create > Droplets > Region Singapore > Ubuntu 24.04 LTS
3. Basic Regular 1 GB RAM ($6/เดือน) > Weekly Backups (+20%, ทางเลือก)
4. เลือก SSH Key หากเตรียมผ่าน Termius ได้ (ปลอดภัยกว่า Password)
5. กด Create Droplet และเปิด Web Console จากหน้าของ Droplet

ขั้นตอน D: ติดตั้งโปรแกรมบน Droplet
คัดลอกทีละคำสั่งใน Web Console โดยแก้ YOUR_GITHUB_USERNAME ตามบัญชีของคุณ:

sudo apt update && sudo apt install -y git python3 nano
sudo git clone https://github.com/YOUR_GITHUB_USERNAME/binance-th-paperbot.git /opt/cryptobot
cd /opt/cryptobot
sudo bash install.sh

ขั้นตอน E: ตั้ง Telegram และทดสอบ
เปิดไฟล์ตั้งค่า:

sudo nano /opt/cryptobot/.env

เติม TELEGRAM_BOT_TOKEN=โทเคนจาก_BotFather
บันทึกไฟล์ nano: Ctrl+O, Enter, Ctrl+X
ลองเช็ก Chat ID:

cd /opt/cryptobot
sudo python3 bot.py chatid

คัดลอกตัวเลขที่ขึ้นหลัง TELEGRAM_CHAT_ID= แล้วกลับไปใส่ใน .env:

sudo nano /opt/cryptobot/.env

จากนั้นทดสอบข้อมูลจริง:

python3 bot.py doctor
sudo -u paperbot python3 bot.py once
sudo -u paperbot python3 bot.py status

หากมี 403 / 429 / invalid symbol ให้หยุดและแก้สาเหตุก่อน ไม่ควรฝืนเรียก API ต่อเนื่อง

ขั้นตอน F: ให้ทำงานต่อเนื่อง 24 ชั่วโมง

sudo systemctl start cryptobot
sudo systemctl status cryptobot --no-pager
sudo journalctl -u cryptobot -n 40 --no-pager

ทดสอบปิดหน้าจอ iPad แล้วรอข้อความแจ้งเตือนใน Telegram
หรือรีสตาร์ต Droplet แล้วตรวจว่าระบบกลับมาทำงานอัตโนมัติ

ดูสถานะล่าสุด:

sudo -u paperbot python3 /opt/cryptobot/bot.py status

หยุดบอท:

sudo systemctl stop cryptobot

หากต้องการหยุดค่าใช้จ่าย VPS ต้อง Destroy Droplet บน DigitalOcean
(การกด Power Off อย่างเดียวอาจยังมีค่าบริการทรัพยากร)

ข้อจำกัดของรุ่นทดลอง
- สแกนข้อมูลทุก 60 วินาที ไม่ใช่ความเร็วระดับมิลลิวินาที
- จำลองการเทรดเฉพาะ BTC/THB ขณะที่ติดตามราคา ETH/THB และ SOL/THB
- ไม่มีเว็บ Dashboard; แสดงสถานะผ่าน Terminal และ Telegram
- ควรทดสอบอย่างน้อย 2-4 สัปดาห์และดูผลหลังหักต้นทุน
- ไม่มีระบบ AI ที่ปรับกลยุทธ์อัตโนมัติหรือระบบ Arbitrage ข้าม Exchange ในเวอร์ชันนี้

แหล่งข้อมูล
Binance TH API: https://www.binance.th/api-docs/en/
Binance TH ค่าธรรมเนียม: https://www.binance.th/th/faq/spot-trading/0e9f70a2b6ed49e4884b2ee0aed26051
DigitalOcean VPS: https://www.digitalocean.com/pricing/droplets
Telegram: https://core.telegram.org/bots/tutorial
