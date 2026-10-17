import React, {useState} from 'react';
import {Anchor, ArrowLeft, ArrowRight, Eye, EyeOff, KeyRound, ShieldCheck, Users, Building2, Database, FolderInput, ChevronRight} from 'lucide-react';

type Row=Record<string,any>;
export const roleNames:Record<string,string>={owner:'企业负责人',employee:'项目员工',partner:'货代人员'};
export const go=(route:string)=>{window.location.hash=route;};
export function PasswordField({label,name,autoComplete='current-password',minLength=1}:{label:string;name:string;autoComplete?:string;minLength?:number}){
  const [visible,setVisible]=useState(false),[caps,setCaps]=useState(false);
  return <div className="co-field"><label htmlFor={'pw-'+name}>{label}</label><div className="co-password-input"><input id={'pw-'+name} name={name} type={visible?'text':'password'} required minLength={minLength} maxLength={128} autoComplete={autoComplete} onKeyUp={e=>setCaps(e.getModifierState('CapsLock'))} onBlur={()=>setCaps(false)}/><button type="button" aria-label={(visible?'隐藏':'显示')+label} aria-pressed={visible} onClick={()=>setVisible(!visible)}>{visible?<EyeOff size={18}/>:<Eye size={18}/>}</button></div>{caps&&<small role="status">大写锁定已开启</small>}</div>;
}

export function LoginExperience({setup,space,error,busy,onSubmit,onDemo,onRetry}:{setup:boolean;space:Row;error:string;busy:boolean;onSubmit:(e:React.FormEvent<HTMLFormElement>)=>void;onDemo:()=>void;onRetry:()=>void}){
  const [help,setHelp]=useState(false),[initializing,setInitializing]=useState(false);
  return <div className="co-entry co-auth-layout"><section className="co-intro"><div className="co-brand"><Anchor/>泊序<span>项目物流协同</span></div><div className="co-auth-story"><h1>项目有进展，<br/>运输有交代。</h1><p>从一条发运需求到最后一件签收，<br/>把人员、资料和交付记录连在一起。</p><div className="co-auth-route"><span>项目需求</span><ArrowRight/><span>运输协同</span><ArrowRight/><span>交付确认</span></div></div><small>企业员工与物流伙伴，在各自的授权范围内协作。</small></section><section className="co-login">
    {setup&&!initializing?<><Building2 size={30}/><h2>准备建立企业空间</h2><p>这个空间尚未初始化。由企业负责人完成首次设置后，员工和物流伙伴使用分配的账号登录。</p><button className="btn primary" onClick={()=>setInitializing(true)}>开始首次设置<ArrowRight size={17}/></button>{error&&<div className="co-error" role="alert">{error}</div>}</>:<>
    {setup&&<button className="pl-back" onClick={()=>setInitializing(false)}><ArrowLeft size={16}/>返回首次设置说明</button>}<div className="co-login-icon">{setup?<Building2/>:<KeyRound/>}</div><h2>{setup?'创建企业负责人':'登录工作空间'}</h2><p>{setup?'首次设置完成后，由负责人创建并管理成员。':'使用企业分配的账号，继续处理你的项目和运输。'}</p>
    {error&&<div role="alert" className="co-error">{error}</div>}<form onSubmit={onSubmit} aria-busy={busy}>
      {setup&&<><label>企业名称<input name="company" required maxLength={100} autoComplete="organization"/></label><label>你的姓名<input name="display_name" required maxLength={60} autoComplete="name"/></label></>}
      <label>登录账号<input name="username" required minLength={3} maxLength={60} pattern="[a-zA-Z0-9_.-]+" autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder="输入企业分配的账号"/></label>
      <PasswordField label={setup?'设置密码（至少12位）':'密码'} name="password" minLength={setup?12:1} autoComplete={setup?'new-password':'current-password'}/>
      <button className="btn primary" disabled={busy}>{busy?'正在处理…':setup?'创建并进入企业空间':'登录'}<ArrowRight size={17}/></button>
    </form>{!setup&&<button className="co-login-help" aria-expanded={help} onClick={()=>setHelp(!help)}>无法登录或还没有账号？</button>}{help&&<div className="co-login-help-content"><strong>联系企业负责人核对账号</strong><p>请先检查账号拼写与键盘大小写。首次登录须更改初始密码；账号停用或未分配，需要负责人处理。</p><p>当前尚未提供自助找回密码。请不要把密码发送到聊天或备注中。</p></div>}
    </>}
    {space.demo_url&&!space.demo&&<div className="co-login-demo"><span>先了解怎么使用</span><a href={space.demo_url} target="_blank" rel="noreferrer">进入独立演示空间<ArrowRight size={16}/></a><small>合成资料 · 无需工作账号 · 操作独立保存</small></div>}{space.demo&&<button className="btn secondary" onClick={onDemo} disabled={busy}>进入合成演示</button>}
    {error&&<button className="pl-link" onClick={onRetry}>重新连接</button>}<p className="co-login-note">泊序 · 本机协同试点</p>
  </section></div>;
}

export function SectionHome({kind,owner}:{kind:'settings'|'resources';owner:boolean}){
  const settings=kind==='settings';
  const links=settings?[[Users,'成员与权限','查看成员、创建账号和管理业务授权。','settings?section=members'],[Database,'数据与备份','保存可恢复资料，查看存储与备份记录。','settings?section=backup']]:[[Building2,'合作伙伴','维护货代与快递渠道；登录账号另在企业设置中管理。','projects?view=partners'],[FolderInput,'导入与待确认','导入项目与需求，核对来源后确认写入。','resources?section=imports']];
  return <section className="co-section-home"><div className="pl-heading"><div><h1>{settings?'企业设置':'业务资料'}</h1><p>{settings?'组织管理与资料维护，日常运输继续在工作区处理。':'整理协作对象和来源资料，支持项目与运输执行。'}</p></div></div><div className="co-destination-list">{(!settings||owner)&&links.map(([Icon,title,description,route]:any)=><button key={route} onClick={()=>go(route)}><Icon size={22}/><span><strong>{title}</strong><small>{description}</small></span><ChevronRight size={20}/></button>)}</div></section>;
}

export function AccountHome({identity,onPassword,onLogout,busy}:{identity:Row;onPassword:()=>void;onLogout:()=>void;busy:boolean}){
  return <section className="co-section-home"><div className="pl-heading"><div><h1>个人账号</h1><p>核对当前身份与业务范围，管理登录安全。</p></div></div><section className="co-account-summary"><div className="co-person"><span className="co-avatar">{identity.user.display_name.slice(0,1)}</span><div><h2>{identity.user.display_name}</h2><p>{identity.organization.name}</p></div></div><dl><div><dt>登录账号</dt><dd>{identity.user.username}</dd></div><div><dt>当前身份</dt><dd>{roleNames[identity.user.role]}</dd></div><div><dt>业务范围</dt><dd>{identity.user.role==='owner'?'企业全部项目与运输':identity.user.role==='employee'?'企业已授权的项目':'所属伙伴已获授权的运输委托'}</dd></div></dl><p className="co-note"><ShieldCheck size={16}/> 看不到需要的项目或委托时，请联系企业负责人分配业务范围。</p></section><div className="co-destination-list"><button onClick={onPassword}><KeyRound size={21}/><span><strong>修改密码</strong><small>更改后，其他已登录会话将失效。</small></span><ChevronRight size={20}/></button></div><button className="btn secondary co-logout" onClick={onLogout} disabled={busy}>退出当前账号</button></section>;
}
