#!/usr/bin/env python3
"""Deploy only this app. No NPM SQL/API writes, restarts or port changes."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
PROJECT='dopamine'
LABEL='io.securityops.project'


def run(args,capture=False,check=True):
    result=subprocess.run(args,cwd=ROOT,text=True,capture_output=capture,check=False)
    if check and result.returncode:
        if capture and result.stderr:print(result.stderr.strip(),file=sys.stderr)
        raise RuntimeError('Comando falhou: '+' '.join(args[:5]))
    return result


def inspect(kind,name):
    result=run(['docker',kind,'inspect',name],capture=True,check=False)
    if result.returncode:return None
    values=json.loads(result.stdout)
    return values[0] if len(values)==1 else None


def read_env(path):
    if path.is_symlink():raise RuntimeError('.env não pode ser um link simbólico.')
    values={}
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            if '=' not in line:raise RuntimeError('Formato .env inválido; use KEY=value sem expressões de shell.')
            key,value=line.split('=',1)
            if key in values or not re.fullmatch('[A-Z][A-Z0-9_]*',key) or any(c in value for c in '\r\n\x00'):
                raise RuntimeError('Chave ou valor .env inválido.')
            values[key]=value
    return values


def write_env(path,values):
    if path.is_symlink():raise RuntimeError('.env não pode ser um link simbólico.')
    temporary=path.with_name('.env.pending')
    if temporary.exists() or temporary.is_symlink():raise RuntimeError('Remova apenas .env.pending após verificar uma operação interrompida.')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write('# Segredo local. Não publicar, copiar para imagens ou enviar a repositórios.\n')
            for key,value in values.items():stream.write(key+'='+value+'\n')
            stream.flush();os.fsync(stream.fileno())
        temporary.replace(path);path.chmod(0o600)
    finally:
        if temporary.exists():temporary.unlink()


def choose_npm(name=None):
    if name:
        selected=inspect('container',name)
        if not selected or not selected.get('State',{}).get('Running'):
            raise RuntimeError('O container NPM indicado não está em execução.')
        if any(part in selected.get('Name','').lower() for part in ('rollback','backup','old-')):
            raise RuntimeError('Um container com nome de rollback/backup não será usado automaticamente.')
        return selected
    preferred=inspect('container','npm-attachment')
    if preferred and preferred.get('State',{}).get('Running'):return preferred
    candidates=[]
    result=run(['docker','ps','--format','{{json .}}'],capture=True)
    for line in result.stdout.splitlines():
        entry=json.loads(line)
        name=entry.get('Names','');image=entry.get('Image','')
        if ('nginx-proxy-manager' in image.lower() or 'nginxproxymanager' in name.lower()) and not any(x in name.lower() for x in ('rollback','backup','old-')):
            candidates.append(entry)
    if len(candidates)!=1:
        raise RuntimeError('NPM ativo não identificado sem ambiguidade. Execute fish scripts/deploy.fish --npm NOME_EXATO.')
    return inspect('container',candidates[0]['Names'])


def validate_values(values):
    secret=values.get('SECRET_KEY','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{48,160}',secret) or secret.startswith('CHANGE'):
        raise RuntimeError('SECRET_KEY existente é inválida. Não vou trocar uma chave ativa silenciosamente.')
    site=values.get('SITE_URL','')
    p=urlsplit(site)
    if p.scheme!='https' or not p.hostname or p.path or p.query or p.fragment or p.username or p.password:
        raise RuntimeError('SITE_URL precisa ser uma origem HTTPS, sem caminho ou credenciais.')
    if values.get('ALLOWED_HOSTS')!=p.netloc.lower():
        raise RuntimeError('No deploy padrão, ALLOWED_HOSTS deve coincidir exatamente com o domínio de SITE_URL.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}',values.get('PROXY_NETWORK','')):
        raise RuntimeError('Nome da rede Docker inválido.')
    if not re.fullmatch(r'[A-Za-z0-9_.+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',values.get('CONTACT_EMAIL','')):
        raise RuntimeError('CONTACT_EMAIL precisa ser um contato válido do operador.')


def main():
    parser=argparse.ArgumentParser(description='Deploy isolado do Dopamine junto ao NPM existente.')
    parser.add_argument('--npm',help='nome exato do NPM ativo; padrão: npm-attachment')
    parser.add_argument('--contact',help='e-mail público de privacidade/contato do operador')
    parser.add_argument('--skip-build',action='store_true',help='apenas reconectar rede e aplicar imagem local já construída')
    args=parser.parse_args()
    os.umask(0o077)
    for command in ('docker',):
        if not shutil.which(command):raise RuntimeError(command+' não está instalado.')
    run(['docker','info'],capture=True)
    version=run(['docker','compose','version','--short'],capture=True).stdout.strip()
    match=re.match(r'v?(\d+)\.(\d+)',version)
    if not match or tuple(map(int,match.groups()))<(2,20):
        raise RuntimeError('Use o plugin Docker Compose 2.20 ou superior.')
    npm=choose_npm(args.npm)
    name=npm['Name'].lstrip('/')
    print('NPM existente selecionado: '+name,flush=True)
    env_path=ROOT/'.env'
    values=read_env(env_path)
    if not values:
        values=dict(SECRET_KEY=secrets.token_urlsafe(48),SITE_URL='https://dopamine.securityops.co',
            ALLOWED_HOSTS='dopamine.securityops.co',PROXY_NETWORK='npm-bridge',TRUSTED_PROXY_CIDRS='',
            CONTACT_EMAIL='admin@securityops.co',SECURE_COOKIES='true',REQUIRE_LOCAL_PHOTOS='true')
    if args.contact:values['CONTACT_EMAIL']=args.contact
    values['SECURE_COOKIES']='true';values['REQUIRE_LOCAL_PHOTOS']='true'
    validate_values(values)
    network=values['PROXY_NETWORK']
    current=inspect('network',network)
    if not current or current.get('Driver')!='bridge':
        raise RuntimeError('Use uma rede bridge Docker existente, como npm-bridge. Nenhuma rede será criada ou alterada.')
    if network not in npm.get('NetworkSettings',{}).get('Networks',{}):
        raise RuntimeError('O NPM selecionado não está na rede '+network+'. Preserve a rede de proxy que já funciona.')
    write_env(env_path,values)
    compose=['docker','compose','--project-name',PROJECT,'--file',str(ROOT/'compose.yaml'),'--env-file',str(env_path)]
    run(compose+['config','--quiet'])
    if not args.skip_build:
        print('Construindo imagem, executando testes e importando fotos locais. O NPM ainda não será alterado.',flush=True)
        run(compose+['build','--pull','web'])
    else:
        if not inspect('image','dopamine-local:1.2.1'):raise RuntimeError('Imagem local ausente; execute sem --skip-build.')
    npm=inspect('container',name)
    npm=inspect('container',name)
    endpoint=npm['NetworkSettings']['Networks'][network]
    cidrs=[]
    for key in ('IPAddress','GlobalIPv6Address'):
        address=endpoint.get(key)
        if address:
            ip=ipaddress.ip_address(address);cidrs.append(str(ip)+'/'+str(ip.max_prefixlen))
    if not cidrs:raise RuntimeError('NPM está sem endereço IP na rede compartilhada.')
    values['TRUSTED_PROXY_CIDRS']=','.join(cidrs);write_env(env_path,values)
    run(compose+['up','-d','--no-deps','--wait','--wait-timeout','180','web'])
    run(compose+['exec','-T','web','python','/app/scripts/healthcheck.py'])
    run(compose+['exec','-T','web','python','manage.py','verify-photos'])
    print('\nCONTAINER DOPAMINE SAUDÁVEL. Publicação HTTPS ainda depende de DNS e Proxy Host no NPM.')
    print('NPM: domínio='+values['ALLOWED_HOSTS']+' | scheme=http | hostname=dopamine-web | port=8000')
    print('Ative Force SSL e um certificado válido. Advanced: vazio; WebSocket não é necessário.')
    print('Não substituí, reiniciei ou editei configurações/hosts de outros projetos.')
    print('Contato público configurado: '+values['CONTACT_EMAIL']+' — confirme que esta caixa é atendida.')
    print('Manual: README.md e docs/OPERATIONS.md. Guarde .env e backups fora do webroot.')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (RuntimeError,OSError,ValueError,KeyError) as exc:
        print('\nERRO: '+str(exc),file=sys.stderr)
        print('Nenhum outro serviço será reiniciado automaticamente. Consulte os logs da etapa que falhou.',file=sys.stderr)
        sys.exit(1)
