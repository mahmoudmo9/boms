"""Base data seeded at install: ISO 3166-1 countries, active ISO 4217 currencies, units.

Rows are inserted with ON CONFLICT DO NOTHING, so seeding is idempotent and
never overwrites edits made in the app.
"""

from decimal import Decimal

# iso2|iso3|name_en|name_fa
COUNTRIES_TEXT = """\
AF|AFG|Afghanistan|افغانستان
AX|ALA|Åland Islands|جزایر آلند
AL|ALB|Albania|آلبانی
DZ|DZA|Algeria|الجزایر
AS|ASM|American Samoa|ساموآی آمریکا
AD|AND|Andorra|آندورا
AO|AGO|Angola|آنگولا
AI|AIA|Anguilla|آنگویلا
AQ|ATA|Antarctica|جنوبگان
AG|ATG|Antigua and Barbuda|آنتیگوا و باربودا
AR|ARG|Argentina|آرژانتین
AM|ARM|Armenia|ارمنستان
AW|ABW|Aruba|آروبا
AU|AUS|Australia|استرالیا
AT|AUT|Austria|اتریش
AZ|AZE|Azerbaijan|جمهوری آذربایجان
BS|BHS|Bahamas|باهاما
BH|BHR|Bahrain|بحرین
BD|BGD|Bangladesh|بنگلادش
BB|BRB|Barbados|باربادوس
BY|BLR|Belarus|بلاروس
BE|BEL|Belgium|بلژیک
BZ|BLZ|Belize|بلیز
BJ|BEN|Benin|بنین
BM|BMU|Bermuda|برمودا
BT|BTN|Bhutan|بوتان
BO|BOL|Bolivia|بولیوی
BQ|BES|Bonaire, Sint Eustatius and Saba|جزایر کارائیب هلند
BA|BIH|Bosnia and Herzegovina|بوسنی و هرزگوین
BW|BWA|Botswana|بوتسوانا
BV|BVT|Bouvet Island|جزیره بووه
BR|BRA|Brazil|برزیل
IO|IOT|British Indian Ocean Territory|قلمرو بریتانیا در اقیانوس هند
BN|BRN|Brunei Darussalam|برونئی
BG|BGR|Bulgaria|بلغارستان
BF|BFA|Burkina Faso|بورکینافاسو
BI|BDI|Burundi|بوروندی
CV|CPV|Cabo Verde|کیپ ورد
KH|KHM|Cambodia|کامبوج
CM|CMR|Cameroon|کامرون
CA|CAN|Canada|کانادا
KY|CYM|Cayman Islands|جزایر کیمن
CF|CAF|Central African Republic|جمهوری آفریقای مرکزی
TD|TCD|Chad|چاد
CL|CHL|Chile|شیلی
CN|CHN|China|چین
CX|CXR|Christmas Island|جزیره کریسمس
CC|CCK|Cocos (Keeling) Islands|جزایر کوکوس
CO|COL|Colombia|کلمبیا
KM|COM|Comoros|کومور
CG|COG|Congo|کنگو
CD|COD|Congo, Democratic Republic of the|جمهوری دموکراتیک کنگو
CK|COK|Cook Islands|جزایر کوک
CR|CRI|Costa Rica|کاستاریکا
CI|CIV|Côte d'Ivoire|ساحل عاج
HR|HRV|Croatia|کرواسی
CU|CUB|Cuba|کوبا
CW|CUW|Curaçao|کوراسائو
CY|CYP|Cyprus|قبرس
CZ|CZE|Czechia|جمهوری چک
DK|DNK|Denmark|دانمارک
DJ|DJI|Djibouti|جیبوتی
DM|DMA|Dominica|دومینیکا
DO|DOM|Dominican Republic|جمهوری دومینیکن
EC|ECU|Ecuador|اکوادور
EG|EGY|Egypt|مصر
SV|SLV|El Salvador|السالوادور
GQ|GNQ|Equatorial Guinea|گینه استوایی
ER|ERI|Eritrea|اریتره
EE|EST|Estonia|استونی
SZ|SWZ|Eswatini|اسواتینی
ET|ETH|Ethiopia|اتیوپی
FK|FLK|Falkland Islands (Malvinas)|جزایر فالکلند
FO|FRO|Faroe Islands|جزایر فارو
FJ|FJI|Fiji|فیجی
FI|FIN|Finland|فنلاند
FR|FRA|France|فرانسه
GF|GUF|French Guiana|گویان فرانسه
PF|PYF|French Polynesia|پلی‌نزی فرانسه
TF|ATF|French Southern Territories|سرزمین‌های جنوبی فرانسه
GA|GAB|Gabon|گابن
GM|GMB|Gambia|گامبیا
GE|GEO|Georgia|گرجستان
DE|DEU|Germany|آلمان
GH|GHA|Ghana|غنا
GI|GIB|Gibraltar|جبل‌الطارق
GR|GRC|Greece|یونان
GL|GRL|Greenland|گرینلند
GD|GRD|Grenada|گرنادا
GP|GLP|Guadeloupe|گوادلوپ
GU|GUM|Guam|گوام
GT|GTM|Guatemala|گواتمالا
GG|GGY|Guernsey|گرنزی
GN|GIN|Guinea|گینه
GW|GNB|Guinea-Bissau|گینه بیسائو
GY|GUY|Guyana|گویان
HT|HTI|Haiti|هائیتی
HM|HMD|Heard Island and McDonald Islands|جزیره هرد و جزایر مک‌دونالد
VA|VAT|Holy See|واتیکان
HN|HND|Honduras|هندوراس
HK|HKG|Hong Kong|هنگ کنگ
HU|HUN|Hungary|مجارستان
IS|ISL|Iceland|ایسلند
IN|IND|India|هند
ID|IDN|Indonesia|اندونزی
IR|IRN|Iran|ایران
IQ|IRQ|Iraq|عراق
IE|IRL|Ireland|ایرلند
IM|IMN|Isle of Man|جزیره من
IL|ISR|Israel|اسرائیل
IT|ITA|Italy|ایتالیا
JM|JAM|Jamaica|جامائیکا
JP|JPN|Japan|ژاپن
JE|JEY|Jersey|جرزی
JO|JOR|Jordan|اردن
KZ|KAZ|Kazakhstan|قزاقستان
KE|KEN|Kenya|کنیا
KI|KIR|Kiribati|کیریباتی
KP|PRK|Korea, North|کره شمالی
KR|KOR|Korea, South|کره جنوبی
KW|KWT|Kuwait|کویت
KG|KGZ|Kyrgyzstan|قرقیزستان
LA|LAO|Lao People's Democratic Republic|لائوس
LV|LVA|Latvia|لتونی
LB|LBN|Lebanon|لبنان
LS|LSO|Lesotho|لسوتو
LR|LBR|Liberia|لیبریا
LY|LBY|Libya|لیبی
LI|LIE|Liechtenstein|لیختن‌اشتاین
LT|LTU|Lithuania|لیتوانی
LU|LUX|Luxembourg|لوکزامبورگ
MO|MAC|Macao|ماکائو
MG|MDG|Madagascar|ماداگاسکار
MW|MWI|Malawi|مالاوی
MY|MYS|Malaysia|مالزی
MV|MDV|Maldives|مالدیو
ML|MLI|Mali|مالی
MT|MLT|Malta|مالت
MH|MHL|Marshall Islands|جزایر مارشال
MQ|MTQ|Martinique|مارتینیک
MR|MRT|Mauritania|موریتانی
MU|MUS|Mauritius|موریس
YT|MYT|Mayotte|مایوت
MX|MEX|Mexico|مکزیک
FM|FSM|Micronesia|میکرونزی
MD|MDA|Moldova|مولداوی
MC|MCO|Monaco|موناکو
MN|MNG|Mongolia|مغولستان
ME|MNE|Montenegro|مونته‌نگرو
MS|MSR|Montserrat|مونتسرات
MA|MAR|Morocco|مراکش
MZ|MOZ|Mozambique|موزامبیک
MM|MMR|Myanmar|میانمار
NA|NAM|Namibia|نامیبیا
NR|NRU|Nauru|نائورو
NP|NPL|Nepal|نپال
NL|NLD|Netherlands|هلند
NC|NCL|New Caledonia|کالدونیای جدید
NZ|NZL|New Zealand|نیوزیلند
NI|NIC|Nicaragua|نیکاراگوئه
NE|NER|Niger|نیجر
NG|NGA|Nigeria|نیجریه
NU|NIU|Niue|نیوئه
NF|NFK|Norfolk Island|جزیره نورفک
MK|MKD|North Macedonia|مقدونیه شمالی
MP|MNP|Northern Mariana Islands|جزایر ماریانای شمالی
NO|NOR|Norway|نروژ
OM|OMN|Oman|عمان
PK|PAK|Pakistan|پاکستان
PW|PLW|Palau|پالائو
PS|PSE|Palestine|فلسطین
PA|PAN|Panama|پاناما
PG|PNG|Papua New Guinea|پاپوآ گینه نو
PY|PRY|Paraguay|پاراگوئه
PE|PER|Peru|پرو
PH|PHL|Philippines|فیلیپین
PN|PCN|Pitcairn|جزایر پیت‌کرن
PL|POL|Poland|لهستان
PT|PRT|Portugal|پرتغال
PR|PRI|Puerto Rico|پورتوریکو
QA|QAT|Qatar|قطر
RE|REU|Réunion|رئونیون
RO|ROU|Romania|رومانی
RU|RUS|Russian Federation|روسیه
RW|RWA|Rwanda|رواندا
BL|BLM|Saint Barthélemy|سن بارتلمی
SH|SHN|Saint Helena, Ascension and Tristan da Cunha|سنت هلنا، اسنشن و تریستان دا کونا
KN|KNA|Saint Kitts and Nevis|سنت کیتس و نویس
LC|LCA|Saint Lucia|سنت لوسیا
MF|MAF|Saint Martin (French part)|سن مارتن
PM|SPM|Saint Pierre and Miquelon|سن پیر و میکلن
VC|VCT|Saint Vincent and the Grenadines|سنت وینسنت و گرنادین‌ها
WS|WSM|Samoa|ساموآ
SM|SMR|San Marino|سان مارینو
ST|STP|Sao Tome and Principe|سائوتومه و پرنسیپ
SA|SAU|Saudi Arabia|عربستان سعودی
SN|SEN|Senegal|سنگال
RS|SRB|Serbia|صربستان
SC|SYC|Seychelles|سیشل
SL|SLE|Sierra Leone|سیرالئون
SG|SGP|Singapore|سنگاپور
SX|SXM|Sint Maarten (Dutch part)|سینت مارتن
SK|SVK|Slovakia|اسلواکی
SI|SVN|Slovenia|اسلوونی
SB|SLB|Solomon Islands|جزایر سلیمان
SO|SOM|Somalia|سومالی
ZA|ZAF|South Africa|آفریقای جنوبی
GS|SGS|South Georgia and the South Sandwich Islands|جزایر جورجیای جنوبی و ساندویچ جنوبی
SS|SSD|South Sudan|سودان جنوبی
ES|ESP|Spain|اسپانیا
LK|LKA|Sri Lanka|سری‌لانکا
SD|SDN|Sudan|سودان
SR|SUR|Suriname|سورینام
SJ|SJM|Svalbard and Jan Mayen|سوالبارد و یان ماین
SE|SWE|Sweden|سوئد
CH|CHE|Switzerland|سوئیس
SY|SYR|Syrian Arab Republic|سوریه
TW|TWN|Taiwan|تایوان
TJ|TJK|Tajikistan|تاجیکستان
TZ|TZA|Tanzania|تانزانیا
TH|THA|Thailand|تایلند
TL|TLS|Timor-Leste|تیمور شرقی
TG|TGO|Togo|توگو
TK|TKL|Tokelau|توکلائو
TO|TON|Tonga|تونگا
TT|TTO|Trinidad and Tobago|ترینیداد و توباگو
TN|TUN|Tunisia|تونس
TR|TUR|Türkiye|ترکیه
TM|TKM|Turkmenistan|ترکمنستان
TC|TCA|Turks and Caicos Islands|جزایر تورکس و کایکوس
TV|TUV|Tuvalu|تووالو
UG|UGA|Uganda|اوگاندا
UA|UKR|Ukraine|اوکراین
AE|ARE|United Arab Emirates|امارات متحده عربی
GB|GBR|United Kingdom|بریتانیا
US|USA|United States of America|ایالات متحده آمریکا
UM|UMI|United States Minor Outlying Islands|جزایر کوچک حاشیه‌ای ایالات متحده
UY|URY|Uruguay|اروگوئه
UZ|UZB|Uzbekistan|ازبکستان
VU|VUT|Vanuatu|وانواتو
VE|VEN|Venezuela|ونزوئلا
VN|VNM|Viet Nam|ویتنام
VG|VGB|Virgin Islands (British)|جزایر ویرجین بریتانیا
VI|VIR|Virgin Islands (U.S.)|جزایر ویرجین آمریکا
WF|WLF|Wallis and Futuna|والیس و فوتونا
EH|ESH|Western Sahara|صحرای غربی
YE|YEM|Yemen|یمن
ZM|ZMB|Zambia|زامبیا
ZW|ZWE|Zimbabwe|زیمبابوه
"""

# Countries listed first in pickers (lower sort_order first); everything else is 100.
COUNTRY_SORT = {"IR": 1, "AE": 2, "TR": 3, "CN": 4, "IQ": 5, "AF": 6, "RU": 7, "IN": 8}

# code|minor_units|symbol|name_en|name_fa  (active ISO 4217 currencies)
CURRENCIES_TEXT = """\
AED|2|د.إ|UAE Dirham|درهم امارات
AFN|2|؋|Afghani|افغانی افغانستان
ALL|2|L|Lek|لک آلبانی
AMD|2|֏|Armenian Dram|درام ارمنستان
AOA|2|Kz|Kwanza|کوانزای آنگولا
ARS|2|$|Argentine Peso|پزوی آرژانتین
AUD|2|A$|Australian Dollar|دلار استرالیا
AWG|2|ƒ|Aruban Florin|فلورین آروبا
AZN|2|₼|Azerbaijan Manat|منات آذربایجان
BAM|2|KM|Convertible Mark|مارک تبدیل‌پذیر بوسنی
BBD|2|$|Barbados Dollar|دلار باربادوس
BDT|2|৳|Taka|تاکای بنگلادش
BHD|3|.د.ب|Bahraini Dinar|دینار بحرین
BIF|0|FBu|Burundi Franc|فرانک بوروندی
BMD|2|$|Bermudian Dollar|دلار برمودا
BND|2|$|Brunei Dollar|دلار برونئی
BOB|2|Bs|Boliviano|بولیویانوی بولیوی
BRL|2|R$|Brazilian Real|رئال برزیل
BSD|2|$|Bahamian Dollar|دلار باهاما
BTN|2|Nu.|Ngultrum|انگولترام بوتان
BWP|2|P|Pula|پولای بوتسوانا
BYN|2|Br|Belarusian Ruble|روبل بلاروس
BZD|2|$|Belize Dollar|دلار بلیز
CAD|2|C$|Canadian Dollar|دلار کانادا
CDF|2|FC|Congolese Franc|فرانک کنگو
CHF|2|CHF|Swiss Franc|فرانک سوئیس
CLP|0|$|Chilean Peso|پزوی شیلی
CNY|2|¥|Yuan Renminbi|یوان چین
COP|2|$|Colombian Peso|پزوی کلمبیا
CRC|2|₡|Costa Rican Colon|کولون کاستاریکا
CUP|2|$|Cuban Peso|پزوی کوبا
CVE|2|$|Cabo Verde Escudo|اسکودوی کیپ ورد
CZK|2|Kč|Czech Koruna|کرون چک
DJF|0|Fdj|Djibouti Franc|فرانک جیبوتی
DKK|2|kr|Danish Krone|کرون دانمارک
DOP|2|$|Dominican Peso|پزوی دومینیکن
DZD|2|د.ج|Algerian Dinar|دینار الجزایر
EGP|2|ج.م|Egyptian Pound|پوند مصر
ERN|2|Nfk|Nakfa|ناکفای اریتره
ETB|2|Br|Ethiopian Birr|بیر اتیوپی
EUR|2|€|Euro|یورو
FJD|2|$|Fiji Dollar|دلار فیجی
FKP|2|£|Falkland Islands Pound|پوند جزایر فالکلند
GBP|2|£|Pound Sterling|پوند استرلینگ
GEL|2|₾|Lari|لاری گرجستان
GHS|2|₵|Ghana Cedi|سدی غنا
GIP|2|£|Gibraltar Pound|پوند جبل‌الطارق
GMD|2|D|Dalasi|دالاسی گامبیا
GNF|0|FG|Guinean Franc|فرانک گینه
GTQ|2|Q|Quetzal|کتزال گواتمالا
GYD|2|$|Guyana Dollar|دلار گویان
HKD|2|HK$|Hong Kong Dollar|دلار هنگ کنگ
HNL|2|L|Lempira|لمپیرای هندوراس
HTG|2|G|Gourde|گورد هائیتی
HUF|2|Ft|Forint|فورینت مجارستان
IDR|2|Rp|Rupiah|روپیه اندونزی
ILS|2|₪|New Israeli Sheqel|شکل اسرائیل
INR|2|₹|Indian Rupee|روپیه هند
IQD|3|ع.د|Iraqi Dinar|دینار عراق
IRR|2|﷼|Iranian Rial|ریال ایران
ISK|0|kr|Iceland Krona|کرون ایسلند
JMD|2|$|Jamaican Dollar|دلار جامائیکا
JOD|3|د.ا|Jordanian Dinar|دینار اردن
JPY|0|¥|Yen|ین ژاپن
KES|2|KSh|Kenyan Shilling|شیلینگ کنیا
KGS|2|сом|Som|سوم قرقیزستان
KHR|2|៛|Riel|ریل کامبوج
KMF|0|CF|Comorian Franc|فرانک کومور
KPW|2|₩|North Korean Won|وون کره شمالی
KRW|0|₩|Won|وون کره جنوبی
KWD|3|د.ك|Kuwaiti Dinar|دینار کویت
KYD|2|$|Cayman Islands Dollar|دلار جزایر کیمن
KZT|2|₸|Tenge|تنگه قزاقستان
LAK|2|₭|Lao Kip|کیپ لائوس
LBP|2|ل.ل|Lebanese Pound|لیره لبنان
LKR|2|Rs|Sri Lanka Rupee|روپیه سری‌لانکا
LRD|2|$|Liberian Dollar|دلار لیبریا
LSL|2|L|Loti|لوتی لسوتو
LYD|3|ل.د|Libyan Dinar|دینار لیبی
MAD|2|د.م.|Moroccan Dirham|درهم مراکش
MDL|2|L|Moldovan Leu|لئوی مولداوی
MGA|2|Ar|Malagasy Ariary|آریاری ماداگاسکار
MKD|2|ден|Denar|دینار مقدونیه
MMK|2|K|Kyat|کیات میانمار
MNT|2|₮|Tugrik|توگریک مغولستان
MOP|2|MOP$|Pataca|پاتاکای ماکائو
MRU|2|UM|Ouguiya|اوگیه موریتانی
MUR|2|₨|Mauritius Rupee|روپیه موریس
MVR|2|Rf|Rufiyaa|روفیه مالدیو
MWK|2|MK|Malawi Kwacha|کواچای مالاوی
MXN|2|$|Mexican Peso|پزوی مکزیک
MYR|2|RM|Malaysian Ringgit|رینگیت مالزی
MZN|2|MT|Mozambique Metical|متیکال موزامبیک
NAD|2|$|Namibia Dollar|دلار نامیبیا
NGN|2|₦|Naira|نایرای نیجریه
NIO|2|C$|Cordoba Oro|کوردوبای نیکاراگوئه
NOK|2|kr|Norwegian Krone|کرون نروژ
NPR|2|₨|Nepalese Rupee|روپیه نپال
NZD|2|NZ$|New Zealand Dollar|دلار نیوزیلند
OMR|3|ر.ع.|Rial Omani|ریال عمان
PAB|2|B/.|Balboa|بالبوای پاناما
PEN|2|S/|Sol|سول پرو
PGK|2|K|Kina|کینای پاپوآ گینه نو
PHP|2|₱|Philippine Peso|پزوی فیلیپین
PKR|2|₨|Pakistan Rupee|روپیه پاکستان
PLN|2|zł|Zloty|زلوتی لهستان
PYG|0|₲|Guarani|گوارانی پاراگوئه
QAR|2|ر.ق|Qatari Rial|ریال قطر
RON|2|lei|Romanian Leu|لئوی رومانی
RSD|2|дин.|Serbian Dinar|دینار صربستان
RUB|2|₽|Russian Ruble|روبل روسیه
RWF|0|FRw|Rwanda Franc|فرانک رواندا
SAR|2|ر.س|Saudi Riyal|ریال عربستان
SBD|2|$|Solomon Islands Dollar|دلار جزایر سلیمان
SCR|2|₨|Seychelles Rupee|روپیه سیشل
SDG|2|ج.س.|Sudanese Pound|پوند سودان
SEK|2|kr|Swedish Krona|کرون سوئد
SGD|2|S$|Singapore Dollar|دلار سنگاپور
SHP|2|£|Saint Helena Pound|پوند سنت هلنا
SLE|2|Le|Leone|لئونه سیرالئون
SOS|2|Sh|Somali Shilling|شیلینگ سومالی
SRD|2|$|Surinam Dollar|دلار سورینام
SSP|2|£|South Sudanese Pound|پوند سودان جنوبی
STN|2|Db|Dobra|دوبرای سائوتومه
SVC|2|₡|El Salvador Colon|کولون السالوادور
SYP|2|ل.س|Syrian Pound|لیره سوریه
SZL|2|L|Lilangeni|لیلانگنی اسواتینی
THB|2|฿|Baht|بات تایلند
TJS|2|SM|Somoni|سامانی تاجیکستان
TMT|2|m|Turkmenistan New Manat|منات ترکمنستان
TND|3|د.ت|Tunisian Dinar|دینار تونس
TOP|2|T$|Pa'anga|پاآنگای تونگا
TRY|2|₺|Turkish Lira|لیر ترکیه
TTD|2|$|Trinidad and Tobago Dollar|دلار ترینیداد و توباگو
TWD|2|NT$|New Taiwan Dollar|دلار تایوان
TZS|2|TSh|Tanzanian Shilling|شیلینگ تانزانیا
UAH|2|₴|Hryvnia|گریونای اوکراین
UGX|0|USh|Uganda Shilling|شیلینگ اوگاندا
USD|2|$|US Dollar|دلار آمریکا
UYU|2|$|Peso Uruguayo|پزوی اروگوئه
UZS|2|soʻm|Uzbekistan Sum|سوم ازبکستان
VED|2|Bs.D|Bolívar Soberano (digital)|بولیوار سوبرانو (دیجیتال)
VES|2|Bs.S|Bolívar Soberano|بولیوار ونزوئلا
VND|0|₫|Dong|دونگ ویتنام
VUV|0|VT|Vatu|واتوی وانواتو
WST|2|T|Tala|تالای ساموآ
XAF|0|FCFA|CFA Franc BEAC|فرانک سی‌اف‌آ مرکزی
XCD|2|EC$|East Caribbean Dollar|دلار کارائیب شرقی
XCG|2|Cg|Caribbean Guilder|گیلدر کارائیب
XOF|0|CFA|CFA Franc BCEAO|فرانک سی‌اف‌آ غربی
XPF|0|₣|CFP Franc|فرانک سی‌اف‌پی
YER|2|﷼|Yemeni Rial|ریال یمن
ZAR|2|R|Rand|راند آفریقای جنوبی
ZMW|2|ZK|Zambian Kwacha|کواچای زامبیا
ZWG|2|ZiG|Zimbabwe Gold|طلای زیمبابوه
"""

# code|kind|base_factor|name_en|name_fa
# Base units per kind: count=piece, weight=kg, length=m, area=m2, volume=m3, time=second.
# kind "other" = packaging units without a fixed conversion (base_factor 1, not convertible).
UNITS_TEXT = """\
pc|count|1|Piece|عدد
pair|count|2|Pair|جفت
dozen|count|12|Dozen|دوجین
set|other|1|Set|ست
box|other|1|Box|جعبه
carton|other|1|Carton|کارتن
pallet|other|1|Pallet|پالت
roll|other|1|Roll|رول
drum|other|1|Drum|بشکه (درام)
bag|other|1|Bag|کیسه
bundle|other|1|Bundle|بسته
coil|other|1|Coil|کلاف
cont20|other|1|Container 20 ft|کانتینر ۲۰ فوت
cont40|other|1|Container 40 ft|کانتینر ۴۰ فوت
mg|weight|0.000001|Milligram|میلی‌گرم
g|weight|0.001|Gram|گرم
kg|weight|1|Kilogram|کیلوگرم
t|weight|1000|Metric ton|تن
lb|weight|0.45359237|Pound|پوند
oz|weight|0.028349523125|Ounce|اونس
mm|length|0.001|Millimetre|میلی‌متر
cm|length|0.01|Centimetre|سانتی‌متر
m|length|1|Metre|متر
km|length|1000|Kilometre|کیلومتر
in|length|0.0254|Inch|اینچ
ft|length|0.3048|Foot|فوت
cm2|area|0.0001|Square centimetre|سانتی‌متر مربع
m2|area|1|Square metre|متر مربع
ha|area|10000|Hectare|هکتار
ml|volume|0.000001|Millilitre|میلی‌لیتر
l|volume|0.001|Litre|لیتر
m3|volume|1|Cubic metre|متر مکعب
gal|volume|0.003785411784|US gallon|گالن آمریکایی
bbl|volume|0.158987294928|Oil barrel|بشکه نفت
s|time|1|Second|ثانیه
min|time|60|Minute|دقیقه
h|time|3600|Hour|ساعت
day|time|86400|Day|روز
week|time|604800|Week|هفته
"""


def _rows(text: str) -> list[list[str]]:
    return [line.split("|") for line in text.strip().splitlines()]


def countries() -> list[dict]:
    return [
        {"iso2": a, "iso3": b, "name_en": en, "name_fa": fa, "sort_order": COUNTRY_SORT.get(a, 100)}
        for a, b, en, fa in _rows(COUNTRIES_TEXT)
    ]


def currencies() -> list[dict]:
    return [
        {"code": c, "minor_units": int(m), "symbol": s, "name_en": en, "name_fa": fa}
        for c, m, s, en, fa in _rows(CURRENCIES_TEXT)
    ]


def units() -> list[dict]:
    return [
        {"code": c, "kind": k, "base_factor": Decimal(f), "name_en": en, "name_fa": fa}
        for c, k, f, en, fa in _rows(UNITS_TEXT)
    ]


def seed(conn) -> dict[str, int]:
    """Insert missing base data rows. `conn` is a SQLAlchemy Connection. Returns rows inserted per table."""
    from sqlalchemy import text

    inserted = {}
    for table, rows, cols, pk in (
        ("sys.country", countries(), ["iso2", "iso3", "name_en", "name_fa", "sort_order"], "iso2"),
        ("sys.currency", currencies(), ["code", "minor_units", "symbol", "name_en", "name_fa"], "code"),
        ("sys.unit", units(), ["code", "kind", "base_factor", "name_en", "name_fa"], "code"),
    ):
        stmt = text(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
            f"ON CONFLICT ({pk}) DO NOTHING"
        )
        inserted[table] = sum(conn.execute(stmt, row).rowcount for row in rows)
    return inserted
