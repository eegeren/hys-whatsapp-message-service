import sys,os,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from dotenv import dotenv_values
from app.core import settings
values=dotenv_values(root/'.env')
print('CONFIG_FILE:',settings.model_config.get('env_file'))
for key in ['META_ACCESS_TOKEN','META_PHONE_NUMBER_ID','META_WABA_ID','META_APP_SECRET','META_VERIFY_TOKEN','META_GRAPH_API_VERSION']:
    print(key, 'ortamda_var=',key in os.environ,'ortam_bos=',os.environ.get(key)=='' ,'dosyayla_eslesiyor=',getattr(settings,key.lower())==values.get(key))
