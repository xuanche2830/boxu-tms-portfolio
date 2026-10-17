import React, {useCallback, useEffect, useState} from 'react';
import {ArrowDownToLine, CheckCircle2, ClipboardList, FileText, FileUp, RefreshCw} from 'lucide-react';
import './evidence.css';

type Row=Record<string,any>;
type Props={api:(path:string,init?:RequestInit)=>Promise<any>;orderId:string;units:Row[];internal?:boolean};
const kinds:Record<string,string>={delivery_receipt:'签收回单',transport_document:'运输单据',cargo_photo:'货物照片',damage_photo:'异常照片',other:'其他凭证'};
const states:Record<string,string>={pending:'待复核',approved:'复核通过',rejected:'需补充材料',missing:'待补材料',pending_review:'已提交，待复核'};
const displayTime=(value:string)=>new Date(value).toLocaleString('zh-CN',{hour12:false,timeZone:'Asia/Shanghai'});

export default function EvidencePanel({api,orderId,units,internal=true}:Props){
  const base='/project-logistics/orders/'+encodeURIComponent(orderId);
  const [data,setData]=useState<Row|null>(null),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [uploadOpen,setUploadOpen]=useState(false);
  const [file,setFile]=useState<File|null>(null),[fileInputKey,setFileInputKey]=useState(0);
  const [kind,setKind]=useState('delivery_receipt'),[unitId,setUnitId]=useState(''),[requirementId,setRequirementId]=useState(''),[note,setNote]=useState('');
  const [uploadKey,setUploadKey]=useState(()=>crypto.randomUUID()),[requireKey,setRequireKey]=useState(()=>crypto.randomUUID());
  const [reviewing,setReviewing]=useState(''),[reviewKey,setReviewKey]=useState(()=>crypto.randomUUID());
  const [reviewNote,setReviewNote]=useState(''),[outcome,setOutcome]=useState('approved');
  const load=useCallback(async()=>{const result=await api('/project-logistics/orders/'+encodeURIComponent(orderId)+'/evidence');setData(result);},[api,orderId]);
  useEffect(()=>{let active=true;setLoading(true);setError('');setData(null);api(base+'/evidence').then(result=>{if(active){setData(result);setUploadOpen(result.files.length===0);}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[api,orderId]);
  async function run(action:()=>Promise<void>){if(busy)return;setBusy(true);setError('');setMessage('');try{await action();}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  function changed(){setUploadKey(crypto.randomUUID());}
  function chooseRequirement(value:string){setUploadOpen(true);setRequirementId(value);const r=data?.requirements.find((r:Row)=>r.id===value);if(r){setKind(r.kind);setUnitId(r.unit_id||'');}changed();}
  async function upload(e:React.FormEvent){e.preventDefault();if(!file)return;await run(async()=>{
    if(file.size<1||file.size>2*1024*1024)throw new Error('每件附件须为1字节至2 MiB，请压缩或拆分后上传。');
    if(!/\.(pdf|png|jpe?g)$/i.test(file.name))throw new Error('请选择 PDF、PNG 或 JPG / JPEG 文件。');
    const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let start=0;start<bytes.length;start+=8192)binary+=String.fromCharCode(...bytes.subarray(start,start+8192));
    const result=await api(base+'/evidence',{method:'POST',body:JSON.stringify({command_id:uploadKey,filename:file.name,source_base64:btoa(binary),kind,unit_id:unitId||null,requirement_id:requirementId||null,note})});
    setMessage(result.replayed?'这件凭证已保存，没有重复上传。':'凭证已上传，等待企业内部复核；运输状态未改变。');setFile(null);setFileInputKey(v=>v+1);setNote('');setUploadKey(crypto.randomUUID());await load();
  });}
  async function requestEvidence(e:React.FormEvent<HTMLFormElement>){e.preventDefault();const form=e.currentTarget;const values=Object.fromEntries(new FormData(form));await run(async()=>{
    await api(base+'/evidence-requirements',{method:'POST',body:JSON.stringify({command_id:requireKey,kind:values.kind,unit_id:values.unit_id||null,note:values.note})});
    setMessage('待补要求已登记，本票获授权成员可以查看和提交。');form.reset();setRequireKey(crypto.randomUUID());await load();
  });}
  function startReview(id:string){setReviewing(reviewing===id?'':id);setReviewNote('');setOutcome('approved');setReviewKey(crypto.randomUUID());}
  async function review(e:React.FormEvent,record:Row){e.preventDefault();await run(async()=>{
    await api(base+'/evidence/'+record.id+'/reviews',{method:'POST',body:JSON.stringify({command_id:reviewKey,version:record.version,outcome,note:reviewNote})});
    setMessage('复核结果已记录，历史记录保留。附件复核不会代替按件签收或关单。');setReviewing('');await load();
  });}
  async function download(record:Row){await run(async()=>{
    // The shared API helper parses JSON; binary downloads use the same-origin cookie directly.
    const response=await fetch(record.download_url,{credentials:'same-origin'});
    if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==='string'?body.detail:'附件下载失败，请刷新后重试。');}
    const blob=await response.blob(),url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=record.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });}
  const canReview=internal&&data?.access.review,canRequest=internal&&data?.access.request;
  const unitLabel=(id:string|null)=>id?units.find(u=>u.id===id)?.label||'指定单件':'整票运输';
  return <section className="ev-panel" aria-label="运输凭证与交付复核"><div className="ev-heading"><div><h2>运输凭证</h2><p>凭证、材料说明和复核结论向本票获授权成员开放。上传不会自动认定签收，也不会单独阻止关单。</p></div><button className="btn secondary" disabled={busy||loading} onClick={()=>run(load)}><RefreshCw size={16}/>刷新</button></div>
    {error&&<div className="pl-error" role="alert">{error}</div>}{message&&<div className="pl-success" role="status"><CheckCircle2 size={17}/>{message}</div>}
    {loading?<div className="ev-loading" role="status">正在载入本票凭证…</div>:data&&<>
      <section className="ev-section"><div className="ev-section-heading"><h3><ClipboardList size={18}/>待补与复核</h3><span>{data.requirements.filter((r:Row)=>r.status!=='approved').length} 项待跟进</span></div>
        {!data.requirements.length?<p className="ev-empty-copy">尚未登记待补要求。可直接上传已有材料{canRequest?'，或明确需要补充的凭证':''}。</p>:<ul className="ev-requirements">{data.requirements.map((r:Row)=><li key={r.id}><div><strong>{kinds[r.kind]} · {unitLabel(r.unit_id)}</strong><span className={'ev-status '+r.status}>{states[r.status]}</span><p>{r.note}</p><small>{r.created_by_name} · {displayTime(r.created_at)}</small></div>{r.status!=='approved'&&<button type="button" className="btn secondary" disabled={busy} onClick={()=>{chooseRequirement(r.id);setTimeout(()=>document.getElementById('evidence-upload-file-'+orderId)?.focus(),0);}}>为此要求上传</button>}</li>)}</ul>}
        {canRequest&&<details className="ev-request-form"><summary>登记一项待补要求</summary><form onSubmit={requestEvidence} onChange={()=>setRequireKey(crypto.randomUUID())}><fieldset disabled={busy}><div className="ev-fields"><label>凭证类型<select name="kind" defaultValue="delivery_receipt">{Object.entries(kinds).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>关联范围<select name="unit_id"><option value="">整票运输</option>{units.map(u=><option key={u.id} value={u.id}>{u.label}</option>)}</select></label><label className="ev-wide">需要补充的内容<textarea name="note" required maxLength={1000} rows={2} placeholder="例如：补充第2箱的签收回单，并保留收货日期与签收人。"/></label></div><p className="ev-help">内容会向本票获授权货代显示，请只填写协作所需信息。</p><button className="btn secondary" disabled={busy}>保存待补要求</button></fieldset></form></details>}
      </section>
      <section className="ev-section"><div className="ev-section-heading"><h3><FileText size={18}/>已提交的凭证</h3><span>{data.files.length} 件</span></div>{!data.files.length?<div className="ev-empty"><FileText size={28}/><p>本票还没有附件。上传后可追溯提交人、时间及每次复核结论。</p></div>:<div className="ev-files">{data.files.map((record:Row)=><article key={record.id} className="ev-file"><div className="ev-file-heading"><div><strong>{record.filename}</strong><p>{kinds[record.kind]} · {unitLabel(record.unit_id)} · {(record.byte_size/1024).toFixed(1)} KB</p><small>{record.uploaded_by_name} · {displayTime(record.uploaded_at)}</small></div><span className={'ev-status '+record.review_status}>{states[record.review_status]}</span></div>{record.note&&<p className="ev-file-note">{record.note}</p>}<div className="ev-file-actions"><button className="btn secondary" disabled={busy} onClick={()=>download(record)}><ArrowDownToLine size={15}/>下载原文件</button>{canReview&&<button className="btn secondary" disabled={busy} onClick={()=>startReview(record.id)}>{reviewing===record.id?'收起复核':'记录复核结果'}</button>}</div>
        {reviewing===record.id&&<form className="ev-review-form" onSubmit={e=>review(e,record)}><fieldset disabled={busy}><div className="ev-fields"><label>复核结论<select value={outcome} onChange={e=>{setOutcome(e.target.value);setReviewKey(crypto.randomUUID());}}><option value="approved">材料复核通过</option><option value="rejected">需补充或更正材料</option></select></label><label>依据与说明<textarea required rows={2} maxLength={1000} value={reviewNote} onChange={e=>{setReviewNote(e.target.value);setReviewKey(crypto.randomUUID());}} placeholder="记录核对了哪些内容，或还缺什么。"/></label></div><button className="btn primary" disabled={busy}>保存复核结果</button></fieldset></form>}
        <details className="ev-history"><summary>来源编号与复核历史</summary><p>凭证编号：{record.id}</p><p>SHA-256：{record.sha256}</p>{data.reviews.filter((r:Row)=>r.evidence_id===record.id).length===0?<p>尚无复核记录。</p>:data.reviews.filter((r:Row)=>r.evidence_id===record.id).map((r:Row)=><div className="ev-review-record" key={r.id}><strong>{states[r.outcome]} · {r.reviewer_name}</strong><time>{displayTime(r.created_at)}</time><p>{r.note}</p></div>)}</details>
      </article>)}</div>}</section>
      <details className="ev-section ev-upload-disclosure" open={uploadOpen} onToggle={e=>setUploadOpen(e.currentTarget.open)}><summary>补充上传凭证<span>PDF / 图片 · 每件最多 2 MiB</span></summary><div className="ev-section-heading"><h3><FileUp size={18}/>上传凭证</h3><span>每件最多2 MiB · 本票最多30件</span></div><form onSubmit={upload}><fieldset disabled={busy||data.files.length>=data.max_order_files}><div className="ev-fields"><label>对应待补要求<select value={requirementId} onChange={e=>chooseRequirement(e.target.value)}><option value="">独立补充，不关联待补要求</option>{data.requirements.map((r:Row)=><option key={r.id} value={r.id}>{kinds[r.kind]} · {unitLabel(r.unit_id)} · {r.note.slice(0,35)}</option>)}</select></label><label>凭证类型<select value={kind} disabled={!!requirementId} onChange={e=>{setKind(e.target.value);changed();}}>{Object.entries(kinds).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>关联范围<select value={unitId} disabled={!!requirementId} onChange={e=>{setUnitId(e.target.value);changed();}}><option value="">整票运输</option>{units.map(u=><option key={u.id} value={u.id}>{u.label}</option>)}</select></label><label>选择文件<input key={fileInputKey} id={'evidence-upload-file-'+orderId} type="file" required accept=".pdf,.png,.jpg,.jpeg" onChange={e=>{setFile(e.target.files?.[0]||null);changed();}}/></label><label className="ev-wide">材料说明（选填）<textarea value={note} rows={2} maxLength={1000} onChange={e=>{setNote(e.target.value);changed();}} placeholder="说明材料来源及需要复核的内容；不要包含无关个人资料。"/></label></div><div className="ev-form-footer"><p className="ev-help">支持 PDF、PNG、JPG / JPEG。原文件保存后保持不变，补充材料请再次上传。</p><button className="btn primary" disabled={busy||!file}><FileUp size={16}/>{busy?'正在处理…':'上传到本票'}</button></div></fieldset></form>{data.files.length>=data.max_order_files&&<p className="ev-help">本票已达到30件附件上限，可继续下载和复核已有材料。</p>}</details>
    </>}
  </section>;
}
