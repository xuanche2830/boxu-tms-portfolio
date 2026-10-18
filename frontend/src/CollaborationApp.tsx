import React, {useCallback, useEffect, useRef, useState} from 'react';
import {Anchor, ArrowRight, Building2, FolderOpen, LayoutDashboard, Truck, Menu, Settings, ChevronRight, ArrowLeft} from 'lucide-react';
import ProjectLogistics from './ProjectLogistics';
import ImportPanel from './ImportPanel';
import MaintenancePanel from './MaintenancePanel';
import './collaboration.css';
import './collaboration-design.css';
import './account-experience.css';
import MemberManagement from './MemberManagement';
import {LoginExperience,PasswordField,SectionHome,AccountHome} from './AccountExperience';

import {request, type Identity, type SpaceStatus} from './collaboration-api';
const roles:Record<string,string>={owner:'企业负责人',employee:'项目员工',partner:'货代人员'};

export default function CollaborationApp(){
  const [identity,setIdentity]=useState<Identity|null>(null),[ready,setReady]=useState(false),[setup,setSetup]=useState(false);
  const [page,setPage]=useState(window.location.hash==='#access'?'access':window.location.hash==='#maintenance'?'maintenance':window.location.hash==='#imports'?'imports':'projects'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[password,setPassword]=useState(false);
  const [route,setRoute]=useState(window.location.hash.slice(1)||'projects');
  const [accountNotice,setAccountNotice]=useState('');
  const [space,setSpace]=useState<SpaceStatus>({setup_required:false,version:'',demo:false,desktop:false,demo_url:'',work_url:''}),[navOpen,setNavOpen]=useState(false),[section,setSection]=useState('projects');
  useEffect(()=>{const update=()=>{
    let hash=window.location.hash.slice(1)||'projects';
    const legacy:Record<string,string>={access:'settings?section=members',maintenance:'settings?section=backup',imports:'resources?section=imports'};
    if(legacy[hash]){window.location.replace('#'+legacy[hash]);return;}
    const root=hash.split('?')[0];const params=new URLSearchParams(hash.split('?')[1]||'');
    setRoute(hash);setPage(['settings','resources','account'].includes(root)?root:'projects');
    setSection(params.get('order')?'orders':params.get('project')?'catalog':params.get('view')||'projects');
    window.scrollTo({top:0});setNavOpen(false);setPassword(false);
  };update();window.addEventListener('hashchange',update);return()=>window.removeEventListener('hashchange',update);},[]);
  const identityRef=useRef<Identity|null>(null); identityRef.current=identity;
  const load=useCallback(async()=>{try{const status=await request<SpaceStatus>('/status');setSpace(status);setSetup(status.setup_required);if(!status.setup_required){try{setIdentity(await request<Identity>('/me'));}catch(e:any){if(e.status!==401)throw e;if(status.demo){setIdentity(await request<Identity>('/demo-login',{method:'POST',body:JSON.stringify({role:'owner'})}));}else setIdentity(null);}}setError('');}catch(e:any){setError(e.message);}finally{setReady(true);}},[]);
  useEffect(()=>{document.title='泊序 · 协同空间';load();},[load]);
  useEffect(()=>{if(!identity)return;
    if(page==='settings'&&identity.user.role!=='owner'||page==='resources'&&identity.user.role==='partner')window.location.hash='projects';
  },[identity?.user.id,page]);
  useEffect(()=>{if(!identity)return;const verify=()=>{if(document.visibilityState==='visible')request<Identity>('/me',{},identityRef.current).then(setIdentity).catch((e:any)=>{if(e.status===401){setIdentity(null);setError(e.message);}});};const timer=setInterval(verify,30000);window.addEventListener('focus',verify);return()=>{clearInterval(timer);window.removeEventListener('focus',verify);};},[identity?.user.id]);
  const api=useCallback(async(path:string,init?:RequestInit)=>{try{return await request<any>(path,init,identityRef.current);}catch(e:any){if(e.status===401){setIdentity(null);setError(e.message);}throw e;}},[]);
  async function submitLogin(e:React.FormEvent<HTMLFormElement>){e.preventDefault();if(busy)return;setBusy(true);setError('');const data=Object.fromEntries(new FormData(e.currentTarget));try{const result=await request<Identity>(setup?'/setup':'/login',{method:'POST',body:JSON.stringify(data)});setIdentity(result);setAccountNotice('');setSetup(false);setPage('projects');window.location.hash='projects';}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function runDemo(role:string){if(busy)return;setBusy(true);setError('');setAccountNotice('');try{setIdentity(await request<Identity>('/demo-login',{method:'POST',body:JSON.stringify({role})}));window.location.hash='projects';setPassword(false);}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function logout(){if(busy)return;setBusy(true);try{await api('/logout',{method:'POST',body:'{}'});setIdentity(null);setAccountNotice('');setPassword(false);setPage('projects');window.location.hash='projects';}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function changePassword(e:React.FormEvent<HTMLFormElement>){e.preventDefault();if(busy)return;setBusy(true);setError('');const data=Object.fromEntries(new FormData(e.currentTarget));if(data.new_password!==data.confirm){setError('两次新密码不一致');setBusy(false);return;}delete data.confirm;try{setIdentity(await api('/password',{method:'POST',body:JSON.stringify(data)}));setPassword(false);setAccountNotice('密码已修改，其他已登录会话已失效。');window.location.hash='account';}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function exportData(path:string,name:string){try{const data=await api(path);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e:any){setError(e.message);}}
  if(!ready)return <div className="co-loading" role="status">正在连接工作空间…</div>;
  if(!identity)return <LoginExperience setup={setup} space={space} error={error} busy={busy} onSubmit={submitLogin} onDemo={()=>runDemo('owner')} onRetry={load}/>;
  const jump=(hash:string)=>{window.location.hash=hash;setNavOpen(false);setError('');};
  const settingsSection=new URLSearchParams(route.split('?')[1]||'').get('section');
  const inSettings=page==='settings',inResources=page==='resources'||page==='projects'&&section==='partners';
  const title=page==='account'?'个人账号':inSettings?(settingsSection==='members'?'成员与权限':settingsSection==='backup'?'数据与备份':'企业设置'):page==='resources'?(settingsSection==='imports'?'导入与待确认':'业务资料'):section==='orders'?'运输委托':section==='partners'?'合作伙伴':section==='catalog'?'项目与需求':'工作总览';
  const passwordScreen=<section className="co-section-home"><div className="pl-heading"><div>{!identity.user.must_change_password&&<button className="pl-back" onClick={()=>{setPassword(false);setError('');}}><ArrowLeft size={16}/>个人账号</button>}<h1>{identity.user.must_change_password?'设置你的登录密码':'修改密码'}</h1><p>{identity.user.must_change_password?'首次登录，请将初始密码替换为只有你知道的密码。':'修改后其他已登录会话会失效，当前会话继续保留。'}</p></div></div><form className="co-member-form co-password-form" onSubmit={changePassword}><PasswordField label="当前密码" name="current_password"/><PasswordField label="新密码（至少12位）" name="new_password" minLength={12} autoComplete="new-password"/><PasswordField label="再次输入新密码" name="confirm" minLength={12} autoComplete="new-password"/><button className="btn primary" disabled={busy}>{busy?'正在保存…':'保存新密码'}</button>{identity.user.must_change_password&&<button type="button" className="pl-link" onClick={logout}>退出账号</button>}</form></section>;
  return <div className="co-shell"><a className="co-skip" href="#co-main" onClick={e=>{e.preventDefault();document.getElementById('co-main')?.focus();}}>跳到主要内容</a>
    <aside className={'co-sidebar '+(navOpen?'is-open':'')}><div className="co-brand"><Anchor/>泊序<span>项目物流协同</span></div><p className="co-org"><Building2 size={15}/>{identity.organization.name}</p>
      <button className="co-menu" aria-expanded={navOpen} aria-controls="co-navigation" onClick={()=>setNavOpen(!navOpen)}><Menu size={18}/>工作区导航</button>
      <nav id="co-navigation" aria-label="协同工作区">
        {([['projects','工作总览',LayoutDashboard,'projects'],...(identity.user.role!=='partner'?[['catalog','项目与需求',FolderOpen,'projects?view=catalog']]:[]),['orders',identity.user.role==='partner'?'我的运输':'运输委托',Truck,'projects?view=orders']] as any[]).map(([key,label,Icon,href])=><button key={key} disabled={identity.user.must_change_password} aria-current={page==='projects'&&section===key?'page':undefined} className={page==='projects'&&section===key?'active':''} onClick={()=>jump(href)}><Icon size={19}/>{label}</button>)}
        {identity.user.role!=='partner'&&<><span className="co-nav-group">资料维护</span><button disabled={identity.user.must_change_password} aria-current={inResources?'page':undefined} className={inResources?'active':''} onClick={()=>jump('resources')}><Building2 size={19}/>业务资料</button></>}
      </nav>
      <div className="co-sidebar-bottom">{identity.user.role==='owner'&&<button disabled={identity.user.must_change_password} className={'co-settings-link '+(inSettings?'active':'')} aria-current={inSettings?'page':undefined} onClick={()=>jump('settings')}><Settings size={18}/>企业设置</button>}
        <button className={'co-person co-account-link '+(page==='account'?'active':'')} disabled={identity.user.must_change_password} aria-label="打开个人账号" onClick={()=>{setPassword(false);jump('account');}}><span className="co-avatar" aria-hidden="true">{identity.user.display_name.slice(0,1)}</span><span><strong>{identity.user.display_name}</strong><span className="co-role">{roles[identity.user.role]}</span></span><ChevronRight size={16}/></button>
        {!space.desktop&&!space.demo&&space.demo_url&&<a className="co-demo-entry" href={space.demo_url} target="_blank" rel="noreferrer">体验独立演示<ArrowRight size={16}/></a>}
      </div>
    </aside><div className="co-work"><header className="co-top"><nav aria-label="当前位置" className="co-breadcrumb"><button onClick={()=>jump('projects')} disabled={identity.user.must_change_password}>工作空间</button><ChevronRight size={14}/>{(inSettings&&settingsSection||inResources&&(settingsSection||section==='partners'))&&<><button onClick={()=>jump(inSettings?'settings':'resources')}>{inSettings?'企业设置':'业务资料'}</button><ChevronRight size={14}/></>}<strong>{identity.user.must_change_password?'首次修改密码':password?'修改密码':title}</strong></nav><span><span className="co-connected"/>{roles[identity.user.role]} · 已登录</span></header>
    <main id="co-main" tabIndex={-1}>
      {space.demo&&<section className="co-demo-banner"><div><strong>独立演示空间 · 全部为合成资料</strong><p>可练习运输与资料协作。操作只保存在演示库。</p></div><label>演示身份<select aria-label="演示身份" value={identity.user.role} disabled={busy} onChange={e=>runDemo(e.target.value)}>{Object.entries(roles).map(([key,value])=><option key={key} value={key}>{value}</option>)}</select></label>{space.desktop?<span>切换空间请回到泊序启动窗口</span>:<a href={space.work_url}>返回工作空间</a>}</section>}
      {error&&<div className="co-error" role="alert">{error}</div>}
      {page==='account'&&accountNotice&&!password&&<div className="pl-success" role="status">{accountNotice}<button className="pl-link" onClick={()=>setAccountNotice('')}>知道了</button></div>}
      {password||identity.user.must_change_password?passwordScreen:page==='account'?<AccountHome identity={identity} busy={busy} onPassword={()=>{setPassword(true);setError('');}} onLogout={logout}/>:inSettings&&identity.user.role==='owner'?(settingsSection==='members'?<MemberManagement api={api} route={route}/>:settingsSection==='backup'?<MaintenancePanel api={api}/>:<SectionHome kind="settings" owner/>):page==='resources'&&identity.user.role!=='partner'?(settingsSection==='imports'?<ImportPanel key={identity.user.id} api={api} role={identity.user.role}/>:<SectionHome kind="resources" owner={identity.user.role==='owner'}/>):<ProjectLogistics key={identity.user.id} api={api} mode={space.demo?"demo":"workspace"} onExport={exportData}/>}
    </main><footer><span>泊序 v{space.version||'0.12'} · 本机协同试点</span><span>仅显示当前账号获授权资料</span></footer></div>
  </div>;
}
