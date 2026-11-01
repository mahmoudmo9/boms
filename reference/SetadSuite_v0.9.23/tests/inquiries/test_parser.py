from pathlib import Path

from parser import parse_board, find_pagination, parse_appendix_link, parse_attachments, western_digits
from storage import safe_filename, need_folder, validate_download, record_download, load_manifest, is_downloaded, target_path


def test_board_fixture():
    f = Path(__file__).parent / "fixtures" / "board.txt"
    rows = parse_board(f.read_text(encoding="utf-8"), "https://eproc.setadiran.ir/eproc/needBoardInfo-load.do")
    assert len(rows) == 30
    assert rows[0].need_no == "1105090333000402"
    assert rows[0].request_id == "7590104"
    assert "تعمیر و سرویس و نگهداری 6 دستگاه آسانسور" in rows[0].description
    assert rows[0].detail_url.startswith("https://eproc.setadiran.ir/eproc/purchaseNeedView.do")
    total, page_key = find_pagination(f.read_text(encoding="utf-8"), len(rows))
    assert total == 20
    assert page_key == "d-146909-p"


def test_appendix_link():
    code = '''function anonymousShowAppendix()
    {
        openUniquedWindow('anonymousAppendixDocument.do?method=checkCaptcha' +
            '&docId=5447491' +
            '&docNo=1105020006000271' +
            '&docState=1' +
            '&docType=327', 'appendixDocument', 700, 450);
    }'''
    assert parse_appendix_link(code, "https://eproc.setadiran.ir/eproc/detail.do") == (
        "https://eproc.setadiran.ir/eproc/anonymousAppendixDocument.do?method=checkCaptcha"
        "&docId=5447491&docNo=1105020006000271&docState=1&docType=327"
    )


def test_attachment_html():
    text = '''<table><tbody><tr><td>1</td><td><input type="radio" name="sel" id="r6337606"></td><td>بلبرینگ 135.jpg</td></tr>
    <tr><td>2</td><td><input type="radio" name="sel" id="r6337607"></td><td>شرایط.pdf</td></tr></tbody></table>'''
    files = parse_attachments(text)
    assert [(x.file_id, x.file_name) for x in files] == [
        ("6337606", "بلبرینگ 135.jpg"), ("6337607", "شرایط.pdf")
    ]


def test_local_storage(tmp_path):
    folder = need_folder(tmp_path, "1105093179000506")
    assert folder.name == "1105093179000506"
    assert safe_filename('../FILE.pdf') == "_FILE.pdf"
    path = target_path(folder, "شرایط.pdf", "6337703")
    path.write_bytes(b"%PDF-1.4\nexample")
    validate_download(path)
    manifest = {}
    record_download(folder, manifest, "6337703", "شرایط.pdf", path.name)
    assert is_downloaded(folder, load_manifest(folder), "6337703")
    assert target_path(folder, "شرایط.pdf", "6337704").name == "شرایط__6337704.pdf"


def test_reject_security_html(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_text("<script id='f5_cspm'>test</script>")
    try:
        validate_download(p)
    except ValueError as e:
        assert "HTML" in str(e)
    else:
        assert False, "Should reject HTML"


def test_need_detail_form():
    from parser import parse_need_detail
    f = Path(__file__).parent / "fixtures" / "need_detail.html"
    d = parse_need_detail(f.read_text(encoding="utf-8"))
    assert d["found"]
    fields = dict(d["fields"])
    assert fields["شماره نیاز"] == "1105092378001168"
    assert fields["تاریخ و ساعت اعلان عمومی"] == "1405/07/28 - 14:00"
    assert fields["نام دستگاه خریدار"] == "بیمارستان البرز کرج"
    assert fields["مهلت ارسال پاسخ"].startswith("1405/07/30 ساعت 14:00")
    assert fields["حداقل تاریخ اعتبار قیمت"] == "1405/08/28 ساعت 11:00"
    assert fields["استان محل تحویل"] == "البرز" and fields["شهر محل تحویل"] == "کرج"
    assert fields["طبقه‌بندی موضوعی"] == "کالا"
    assert fields["نوع فرآیند خرید"] == "جزيي"
    assert fields["پرداخت از محل اسناد خزانه اسلامی"] == "خیر"
    assert d["description"] == "کارتریج پلاسما تعداد 150 عدد"
    assert (d["group_label"], d["group"]) == ("گروه کالا", "تجهیزات پزشکی و سلامت")
    assert d["items"]["headers"][2] == "نام کالا"
    assert d["items"]["rows"] == [["1", "--", "استریلایزر پلاسما", "دستگاه", "تجهیزات پزشکی و سلامت", "150", "1405/08/05"]]
    assert d["buyer_note"].startswith("پیش فاکتور دارای کد IRC")
    assert d["attachment_count"] == 0
    # nothing from outside the form (site frame, buttons) leaks in
    assert not any("پاسخ به نياز" in v or "اطلاعات تماس" in v for _, v in d["fields"])


def test_need_detail_missing_form():
    from parser import parse_need_detail
    d = parse_need_detail("<html><body><p>login</p></body></html>")
    assert not d["found"] and d["fields"] == []
