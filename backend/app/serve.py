"""PORT-aware Railway API entry point; no embedded worker."""
import os
import uvicorn
from app.deployment import validate_production

if __name__=='__main__':
    validate_production('api')
    port=int(os.environ.get('PORT','3000'))
    if not 1<=port<=65535:raise RuntimeError('PORT geçersiz.')
    uvicorn.run('app.main:app',host='0.0.0.0',port=port,access_log=False,proxy_headers=False)
