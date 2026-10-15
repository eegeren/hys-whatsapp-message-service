"""One bounded, local-only FFmpeg pipeline. No Meta or remote media access."""
import json,logging,math,os,subprocess,tempfile,time,selectors
from pathlib import Path
from app.core import settings

log=logging.getLogger('hys.video')
def diagnostic(raw):
    text=raw.decode(errors='replace')[-4000:] if isinstance(raw,bytes) else str(raw)[-4000:]
    for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token,settings.panel_proxy_secret):
        if secret:text=text.replace(secret,'[gizli]')
    return text
VIDEO_LIMIT=16_000_000  # conservative decimal 16 MB, below 16 MiB
DEMUXERS='mov,matroska,webm,avi,mpeg,mpegts,h264,hevc,flv,asf'
VIDEO_EXTENSIONS={'.mp4','.mov','.m4v','.mkv','.webm','.avi','.3gp','.3gpp','.mpeg','.mpg','.mts','.m2ts','.wmv','.flv'}

class VideoError(Exception):
    def __init__(self,code,message):self.code=code;self.message=message;super().__init__(message)

def tools_health():
    result={}
    for name,path in [('ffmpeg',settings.ffmpeg_path),('ffprobe',settings.ffprobe_path)]:
        try:
            p=subprocess.run([path,'-version'],capture_output=True,timeout=10,check=True)
            result[name]={'ok':True,'version':p.stdout.decode(errors='replace').splitlines()[0][:150]}
        except Exception:result[name]={'ok':False}
    return result

def check_tools():
    health=tools_health()
    missing=[name for name,state in health.items() if not state['ok']]
    if missing:
        log.error('video_tools_unavailable missing=%s',','.join(missing))
        raise VideoError(missing[0]+'_missing' if len(missing)==1 else 'tools_missing','Sunucuda '+', '.join(missing)+' hazır değil. Railway medya araçları kurulumu kontrol edilmeli.')

def probe(path):
    try:
        result=subprocess.run([settings.ffprobe_path,'-v','error','-protocol_whitelist','file,pipe','-format_whitelist',DEMUXERS,'-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=30,check=True)
        data=json.loads(result.stdout)
    except FileNotFoundError:raise VideoError('ffprobe_missing','Sunucuda FFprobe bulunamadı. Railway imajı güncellenmeli.')
    except subprocess.TimeoutExpired:raise VideoError('probe_timeout','Video incelemesi zaman aşımına uğradı. Dosyayı yeniden dışa aktarıp deneyin.')
    except subprocess.CalledProcessError as e:
        log.error('video_probe_failed returncode=%s diagnostic=%s',e.returncode,diagnostic(e.stderr))
        raise VideoError('unreadable_input','Video dosyası okunamadı; eksik, bozuk veya desteklenmeyen bir dosya olabilir.')
    except (ValueError,KeyError,TypeError):raise VideoError('invalid_probe','Video bilgileri okunamadı. Dosyayı yeniden yükleyin.')
    streams=[s for s in data.get('streams',[]) if not s.get('disposition',{}).get('attached_pic')]
    videos=[s for s in streams if s.get('codec_type')=='video'];audio=[s for s in streams if s.get('codec_type')=='audio']
    if not videos:raise VideoError('no_video','Bu dosyada görüntü kanalı bulunamadı; bir video dosyası seçin.')
    v=videos[0]
    width=int(v.get('width',0));height=int(v.get('height',0))
    if width<=0 or height<=0 or width>8192 or height>8192 or width*height>33_554_432:raise VideoError('resolution_limit','Video çözünürlüğü okunamadı veya güvenli işleme sınırını aşıyor. En fazla 8K video yükleyin.')
    try:duration=float(data.get('format',{}).get('duration') or v.get('duration') or 0)
    except (ValueError,TypeError):duration=0
    if not math.isfinite(duration) or duration<=0:raise VideoError('unknown_duration','Videonun süresi belirlenemedi; dosya eksik veya bozuk olabilir.')
    if duration>settings.video_max_duration_seconds:raise VideoError('duration_limit',f'Video en fazla {settings.video_max_duration_seconds//60} dakika olabilir. Videoyu kısaltın.')
    return {'duration':duration,'video_codec':v.get('codec_name'),'pixel_format':v.get('pix_fmt'),'width':int(v.get('width',0)),'height':int(v.get('height',0)),'audio_codec':audio[0].get('codec_name') if audio else None,'audio_streams':len(audio),'video_streams':len(videos),'format':data.get('format',{}).get('format_name',''),'major_brand':data.get('format',{}).get('tags',{}).get('major_brand','').strip()}

def compatible(info):
    return info['video_codec']=='h264' and info['pixel_format']=='yuv420p' and info['audio_codec'] in (None,'aac') and info['audio_streams']<=1 and info['video_streams']==1

def faststart(path):
    # Parse top-level ISO BMFF boxes; avoid matching codec payload bytes by accident.
    with open(path,'rb') as f:
        total=os.fstat(f.fileno()).st_size;offset=0;moov=mdat=None
        while offset+8<=total:
            f.seek(offset);head=f.read(8);size=int.from_bytes(head[:4],'big');kind=head[4:8]
            if size==1:size=int.from_bytes(f.read(8),'big')
            elif size==0:size=total-offset
            if size<8 or offset+size>total:break
            if kind==b'moov':moov=offset
            elif kind==b'mdat':mdat=offset
            offset+=size
        return moov is not None and mdat is not None and moov<mdat

def execute(args,duration,progress,stop=None):
    """Read FFmpeg progress while a monotonic deadline also covers silent/hung encoders."""
    with tempfile.TemporaryFile() as errors:
        try:p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=errors)
        except FileNotFoundError:raise VideoError('ffmpeg_missing','Sunucuda FFmpeg bulunamadı. Railway imajı güncellenmeli.')
        selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ);deadline=time.monotonic()+settings.video_timeout_seconds
        try:
            while p.poll() is None:
                if stop and stop.is_set():raise VideoError('interrupted','Video işleme hizmeti yeniden başladı. Dosyayı tekrar işleyin.')
                if time.monotonic()>deadline:raise VideoError('conversion_timeout','Video dönüştürme süresi aşıldı. Daha kısa bir video yükleyin.')
                for key,_ in selector.select(.5):
                    line=key.fileobj.readline().decode(errors='replace').strip()
                    if line.startswith('out_time_us='):
                        try:progress(min(.99,int(line.split('=',1)[1])/1_000_000/duration))
                        except ValueError:pass
            if p.returncode:
                errors.seek(0);details=diagnostic(errors.read())
                log.error('video_encode_failed returncode=%s diagnostic=%s',p.returncode,details)
                raise VideoError('encode_failed','Video dönüştürülemedi. Dosya bozuk veya içerdiği codec desteklenmiyor olabilir.')
        finally:
            selector.close()
            if p.poll() is None:
                p.kill();p.wait(timeout=10)
            p.stdout.close()

def prepare_video(source,filename,progress=lambda status,pct:None,stop=None):
    if not source:raise VideoError('empty_input','Video dosyası boş.')
    if len(source)>settings.video_input_limit_mb*1024*1024:raise VideoError('input_too_large',f'Kaynak video en fazla {settings.video_input_limit_mb} MB olabilir.')
    if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:raise VideoError('unsupported_extension','MP4, MOV, MKV, WebM, AVI veya desteklenen başka bir video seçin.')
    check_tools();progress('probing',5)
    with tempfile.TemporaryDirectory(prefix='hys-video-') as directory:
        root=Path(directory);src=root/'input';src.write_bytes(source);src.chmod(0o600)
        info=probe(src);size=len(source);out=root/'output.mp4'
        details={'original':info,'source_size':size,'converted':False,'remuxed':False,'compressed':False}
        if compatible(info) and info['major_brand'] in ('isom','iso2','iso5','iso6','mp41','mp42','avc1','M4V') and size<=VIDEO_LIMIT and faststart(src):
            progress('validating',95);return source,{**details,'output_size':size,'result':info}
        progress('converting',10)
        base=[settings.ffmpeg_path,'-hide_banner','-loglevel','error','-nostdin','-y','-protocol_whitelist','file,pipe','-format_whitelist',DEMUXERS,'-threads','2','-i',str(src),'-map','0:V:0','-map','0:a:0?','-map_metadata','-1','-map_chapters','-1','-threads','2','-progress','pipe:1','-nostats']
        tail=['-movflags','+faststart','-f','mp4',str(out)]
        if compatible(info) and size<=VIDEO_LIMIT:
            execute(base+['-c','copy']+tail,info['duration'],lambda v:progress('converting',10+int(v*75)),stop)
            details['remuxed']=True
        if not details['remuxed'] or out.stat().st_size>VIDEO_LIMIT:
            details['remuxed']=False
            details['converted']=True
            # CRF preserves quality first. Oversized sources use a duration-based VBV budget.
            budget=int((VIDEO_LIMIT*.94*8)/info['duration']);audio_rate=96_000 if info['audio_codec'] else 0
            bitrate=budget-audio_rate
            if bitrate<64_000:raise VideoError('cannot_fit','Bu uzunluktaki video 16 MB içine kullanılabilir kalitede sığmıyor. Videoyu kısaltın.')
            compress=size>VIDEO_LIMIT
            for attempt in range(3):
                rate=int(bitrate*(.8**attempt));edge=1280 if rate>=1_500_000 else 854 if rate>=650_000 else 640 if rate>=250_000 else 426
                scale=f"scale=w='min(iw,{edge})':h='min(ih,{edge})':force_original_aspect_ratio=decrease:force_divisible_by=2"
                opts=['-c:v','libx264','-preset','medium','-pix_fmt','yuv420p','-vf',scale,'-c:a','aac','-b:a','96k','-ac','2']
                opts+=['-b:v',str(rate),'-maxrate',str(rate),'-bufsize',str(rate*2)] if compress or attempt else ['-crf','22']
                execute(base+opts+tail,info['duration'],lambda v:progress('converting',10+int((attempt+v)/3*75)),stop)
                if out.stat().st_size<=VIDEO_LIMIT:break
                compress=True
            details['compressed']=compress
        if not out.exists() or out.stat().st_size<=0 or out.stat().st_size>VIDEO_LIMIT:raise VideoError('output_too_large','Video 16 MB sınırına indirilemedi. Daha kısa bir video yükleyin.')
        progress('validating',92);result=probe(out)
        if not compatible(result) or not faststart(out) or abs(result['duration']-info['duration'])>max(1,info['duration']*.02):raise VideoError('invalid_output','Dönüştürülen video doğrulanamadı. Dosyayı tekrar yükleyin.')
        content=out.read_bytes();return content,{**details,'output_size':len(content),'result':result}
