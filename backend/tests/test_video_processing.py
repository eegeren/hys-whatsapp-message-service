"""Real FFmpeg fixtures; never call Meta. Supply FFMPEG_PATH/FFPROBE_PATH in CI."""
import json,os,shutil,subprocess
from pathlib import Path
import pytest
from app.core import settings
from app import video_processing as video

@pytest.fixture
def binaries(monkeypatch):
    ffmpeg=os.environ.get('FFMPEG_PATH') or shutil.which('ffmpeg');ffprobe=os.environ.get('FFPROBE_PATH') or shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:pytest.skip('Real FFmpeg/FFprobe integration requires installed binaries')
    monkeypatch.setattr(settings,'ffmpeg_path',ffmpeg);monkeypatch.setattr(settings,'ffprobe_path',ffprobe)
    return ffmpeg,ffprobe

def sample(tmp_path,binaries,extension='mp4',codec='libx264',audio='aac',fast=True):
    output=tmp_path/f'input.{extension}'
    args=[binaries[0],'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=128x96:rate=12:duration=1']
    if audio:args+=['-f','lavfi','-i','sine=frequency=880:duration=1']
    args+=['-c:v',codec,'-threads','1']
    if codec=='libx264':args+=['-pix_fmt','yuv420p']
    if audio:args+=['-c:a',audio,'-shortest']
    if extension in ('mp4','mov') and fast:args+=['-movflags','+faststart']
    args+=[str(output)];subprocess.run(args,check=True,capture_output=True,timeout=30)
    return output.read_bytes(),output.name

def test_compatible_passes_through_without_encoding(tmp_path,binaries,monkeypatch):
    raw,name=sample(tmp_path,binaries)
    monkeypatch.setattr(video,'execute',lambda *a,**k:pytest.fail('Compatible faststart video must not be reencoded/remuxed'))
    output,info=video.prepare_video(raw,name)
    assert output==raw and not info['converted'] and not info['remuxed']

def test_compatible_tail_moov_is_remuxed_without_reencoding(tmp_path,binaries):
    raw,name=sample(tmp_path,binaries,fast=False);out,info=video.prepare_video(raw,name)
    assert not info['converted'] and info['remuxed'];path=tmp_path/'out.mp4';path.write_bytes(out)
    assert video.faststart(path) and video.compatible(video.probe(path))

def test_mov_mpeg4_pcm_is_converted_to_h264_aac(tmp_path,binaries):
    raw,name=sample(tmp_path,binaries,'mov','mpeg4','pcm_s16le');events=[]
    out,info=video.prepare_video(raw,name,lambda stage,pct:events.append((stage,pct)))
    assert info['converted'] and info['original']['video_codec']=='mpeg4'
    assert info['original']['audio_codec']=='pcm_s16le' and info['result']['audio_codec']=='aac'
    assert info['result']['pixel_format']=='yuv420p' and info['result']['video_codec']=='h264'
    assert len(out)<=video.VIDEO_LIMIT and any(s=='converting' for s,p in events)
    path=tmp_path/'out.mp4';path.write_bytes(out);assert video.faststart(path)

def test_silent_webm_supported(tmp_path,binaries):
    raw,name=sample(tmp_path,binaries,'webm','libvpx-vp9',None);out,info=video.prepare_video(raw,name)
    assert info['converted'] and info['result']['audio_codec'] is None and info['result']['video_codec']=='h264'

def test_oversized_valid_mp4_is_reduced_and_complete(tmp_path,binaries):
    raw,name=sample(tmp_path,binaries);padding=video.VIDEO_LIMIT+100-len(raw)
    raw+=(padding).to_bytes(4,'big')+b'free'+b'\0'*(padding-8)
    assert len(raw)>video.VIDEO_LIMIT
    out,info=video.prepare_video(raw,name)
    assert len(out)<=video.VIDEO_LIMIT and info['compressed'] and info['converted']
    assert abs(info['result']['duration']-info['original']['duration'])<.5

def test_broken_video_has_specific_read_error(tmp_path,binaries,caplog):
    with pytest.raises(video.VideoError) as e:video.prepare_video(b'broken mp4','bad.mp4')
    assert e.value.code=='unreadable_input' and 'video_probe_failed' in caplog.text

def test_missing_tools_is_not_codec_error(monkeypatch):
    monkeypatch.setattr(settings,'ffprobe_path','/nonexistent/hys-ffprobe')
    with pytest.raises(video.VideoError) as e:video.prepare_video(b'broken mp4','bad.mp4')
    assert e.value.code in ('tools_missing','ffprobe_missing')

def test_tool_failure_timeout_and_diagnostic_redaction(monkeypatch,binaries):
    monkeypatch.setattr(settings,'meta_access_token','super-private-test-secret')
    assert 'super-private-test-secret' not in video.diagnostic(b'failure super-private-test-secret')
    def timeout(*a,**k):raise subprocess.TimeoutExpired('ffprobe',30)
    monkeypatch.setattr(video.subprocess,'run',timeout)
    with pytest.raises(video.VideoError) as e:video.probe(Path('/tmp/test'))
    assert e.value.code=='probe_timeout'

def test_compatible_mov_is_remuxed_as_real_mp4_without_reencoding(tmp_path,binaries):
    raw,name=sample(tmp_path,binaries,'mov','libx264','aac')
    out,info=video.prepare_video(raw,name)
    assert info['original']['major_brand']=='qt'
    assert info['remuxed'] and not info['converted']
    assert info['result']['major_brand']!='qt' and info['result']['video_codec']=='h264'
