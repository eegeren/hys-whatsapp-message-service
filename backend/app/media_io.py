"""Bounded upload reads and byte-only request diagnostics. Never log URLs or contents."""
import logging
from contextvars import ContextVar
from fastapi import HTTPException

log=logging.getLogger('hys.upload')
if not log.handlers:
    log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)
log.propagate=False
upload_metrics=ContextVar('upload_metrics',default=None)

def record_received(size,stream=False):
    metrics=upload_metrics.get()
    if metrics is not None:
        if stream:metrics['streamed']=True
        if stream or not metrics.get('streamed'):metrics['received_bytes']=(metrics['received_bytes'] or 0)+size

def read_upload(file,limit):
    # A dependency or validator may already have consumed this UploadFile.
    file.file.seek(0)
    content=file.file.read(limit+1)
    received=len(content)
    record_received(received)
    if received>limit:raise HTTPException(413,f'Dosya boyutu {limit} bayt sınırını aşıyor; en az {received} bayt alındı.')
    if file.size is not None and received!=file.size:
        raise HTTPException(422,f'Yükleme eksik: multipart {file.size} bayt, okunan {received} bayt.')
    return content
