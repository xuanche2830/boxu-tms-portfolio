import React, {useCallback, useEffect, useState} from 'react';
import {Archive, CheckCircle2, Database, RefreshCw} from 'lucide-react';

type Row = Record<string, any>;
export default function MaintenancePanel({api}:{api:(path:string,init?:RequestInit)=>Promise<any>}){
  const [data,setData]=useState<Row|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const load=useCallback(async()=>{try{setData(await api('/maintenance'));setError('');}catch(e:any){setError(e.message);}},[api]);
  useEffect(()=>{load();},[load]);
  async function backup(){if(busy)return;setBusy(true);setError('');setMessage('');try{const result=await api('/maintenance/backups',{method:'POST',body:'{}'});setMessage(`已保存备份，包含 ${result.records} 条资料。`);await load();}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  return <section className="co-maintenance"><div className="pl-heading"><div><h1>数据与备份</h1><p>查看当前存储状态，在重要变更前保存一份可恢复的资料。</p></div><button className="btn secondary" onClick={load}><RefreshCw size={16}/>刷新状态</button></div>
    {error&&<div className="co-error" role="alert">{error}</div>}{message&&<div className="pl-success" role="status"><CheckCircle2 size={18}/>{message}</div>}
    {!data?<div className="co-loading" role="status">正在读取存储状态…</div>:<>
      <section className="co-storage-summary"><Database size={28}/><div><h2>{data.storage==='sqlite'?'SQLite 本机资料库':'PostgreSQL 资料库'}</h2><p>{data.revision===data.expected_revision?'数据库结构已更新':'数据库结构需要升级'} · {data.revision}</p></div><span>{data.counts.projects} 个项目 / {data.counts.orders} 票委托 / {data.counts.users} 位成员</span></section>
      <section className="pl-panel co-backup-action"><div><h2>保存完整业务与账号</h2><p>保留项目、运输、单号、异常、成员、授权、凭证原文件及复核历史。恢复后需要重新登录。</p><small>备份保存在服务所在电脑的备份目录。含账号验证资料，请按企业内部资料保管。</small></div><button className="btn primary" onClick={backup} disabled={busy}><Archive size={17}/>{busy?'正在制作备份…':'创建本机备份'}</button></section>
      <section className="pl-panel"><div className="pl-panel-title"><div><h2>最近备份</h2><p>最多显示最近 20 份。业务记录导出与可恢复备份分别保存。</p></div></div>{data.backups.length?<div className="pl-table-wrap"><table className="pl-table co-backup-table"><thead><tr><th>创建时间</th><th>文件</th><th>资料条数</th><th>本机文件</th></tr></thead><tbody>{data.backups.map((b:Row)=><tr key={b.file}><td>{new Date(b.created_at).toLocaleString('zh-CN')}</td><td className="pl-code">{b.file}</td><td>{b.records}</td><td>{b.available?'已保存':'文件已移走'}</td></tr>)}</tbody></table></div>:<div className="pl-empty"><Archive size={30}/><h3>还没有备份</h3><p>点击“创建本机备份”，保存当前企业空间。</p></div>}</section>
      <div className="co-restore-note"><h2>恢复到新的资料库</h2><p>恢复工具先检查文件与逐表摘要，再写入空库并核对数量和内容。已有资料的库会拒绝覆盖。</p><p>Windows 使用版：关闭泊序启动窗口后重新打开，点击“从完整备份恢复”，选择备份文件。只接受空白工作空间。源码维护步骤见 docs/EVIDENCE-v011.md；恢复前保留原资料和备份。</p></div>
    </>}
  </section>;
}
