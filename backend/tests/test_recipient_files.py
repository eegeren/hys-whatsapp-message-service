"""Synthetic regression files only; never copy customer spreadsheets into the repo."""
import io
import zipfile
from pathlib import Path
import pytest
from openpyxl import Workbook
from fastapi import HTTPException
from app.recipient_files import read_rows,parse_recipients


def xlsx_bytes():
    book=Workbook();sheet=book.active
    sheet.append(['Telefon','Ad Soyad']);sheet.append(['05321234567','Örnek Kişi'])
    output=io.BytesIO();book.save(output);book.close();return output.getvalue()


@pytest.mark.parametrize('filename',['numbers.xlsx','numbers.xls','NUMBERS.XLS'])
def test_xlsx_content_is_read_even_if_export_extension_is_xls(filename):
    rows=read_rows(xlsx_bytes(),filename)
    assert rows==[['Telefon','Ad Soyad'],['05321234567','Örnek Kişi']]
    assert parse_recipients(rows)['numbers']==['+905321234567']


@pytest.mark.parametrize('filename',['numbers.xls','numbers.xlsx'])
def test_real_legacy_xls_is_detected_from_ole_signature(filename):
    raw=(Path(__file__).parent/'fixtures'/'recipients.xls').read_bytes()
    assert raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
    result=parse_recipients(read_rows(raw,filename))
    assert result['numbers']==['+905321234567','+905331234567']


def test_mislabeled_xls_works_through_bulk_preview_api(client):
    result=client.post('/api/bulk/preview',files={'file':('report.xls',xlsx_bytes(),'application/vnd.ms-excel')})
    assert result.status_code==200,result.text
    assert result.json()['unique_count']==1


@pytest.mark.parametrize('raw,filename,status',[
    (b'PK\x03\x04broken','bad.xls',422),
    (b'x'*(5*1024*1024+1),'large.xls',413),
    (b'A\n'*50002,'rows.csv',422),
])
def test_corruption_and_upload_limits_remain_enforced(raw,filename,status):
    with pytest.raises(HTTPException) as error:read_rows(raw,filename)
    assert error.value.status_code==status


def test_format_detection_does_not_allow_unlisted_extension():
    with pytest.raises(HTTPException) as error:read_rows(xlsx_bytes(),'report.bin')
    assert error.value.status_code==422


def test_expanded_zip_limit_applies_even_when_filename_says_xls():
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr('large.xml',b' '*(40*1024*1024+1))
    with pytest.raises(HTTPException) as error:read_rows(buffer.getvalue(),'report.xls')
    assert error.value.status_code==422
    assert 'çok büyük' in error.value.detail
