"""Scoped evidence submission is separate from delivery and closing decisions."""
import base64
import hashlib
import json
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import collab_auth as auth, collab_policy as policy, project_logistics as business
from . import evidence_storage as storage
from .collab_models import User
from .db import audit, identifier, now
from .evidence_models import EvidenceFile, EvidenceRequirement, EvidenceReview
from .project_models import HandlingUnit, TransportOrder

Kind = Literal['delivery_receipt', 'transport_document', 'cargo_photo', 'damage_photo', 'other']
KINDS = {'delivery_receipt': '签收回单', 'transport_document': '运输单据', 'cargo_photo': '货物照片', 'damage_photo': '异常照片', 'other': '其他凭证'}


class Upload(business.Command):
    filename: str = Field(min_length=1, max_length=180)
    source_base64: str = Field(min_length=1, max_length=2_796_204)
    kind: Kind
    unit_id: str | None = None
    requirement_id: str | None = None
    note: str = Field(default='', max_length=1000)


class RequirementInput(business.Command):
    kind: Kind
    unit_id: str | None = None
    note: str = Field(min_length=1, max_length=1000)


class ReviewInput(business.Versioned):
    outcome: Literal['approved', 'rejected']
    note: str = Field(min_length=1, max_length=1000)


def check_unit(session, order_id, unit_id):
    if unit_id is not None:
        unit = session.get(HandlingUnit, unit_id)
        if not unit or unit.order_id != order_id:
            raise HTTPException(422, '附件或待补要求只能关联本票运输单元')


def file_access(session, order_id, evidence_id):
    policy.order_access(session, order_id)
    record = session.get(EvidenceFile, evidence_id)
    if not record or record.order_id != order_id:
        raise HTTPException(404, '凭证不存在或没有访问权限')
    return record


def public_file(session, record):
    session.refresh(record)
    uploader = session.get(User, record.uploaded_by)
    return {**record.model_dump(exclude={'storage_key', 'signature', 'command_id'}),
            'uploaded_by_name': uploader.display_name if uploader else '已归档成员',
            'download_url': f'/api/collab/project-logistics/orders/{record.order_id}/evidence/{record.id}/download'}


def register(app, signed_in, engine):
    prefix = '/api/collab/project-logistics/orders/{order_id}'

    @app.get(prefix + '/evidence')
    def listing(order_id: str, session: Session = Depends(signed_in)):
        policy.order_access(session, order_id)
        files = session.exec(select(EvidenceFile).where(EvidenceFile.order_id == order_id).order_by(EvidenceFile.uploaded_at.desc())).all()
        requirements = session.exec(select(EvidenceRequirement).where(EvidenceRequirement.order_id == order_id).order_by(EvidenceRequirement.created_at.desc())).all()
        reviews = session.exec(select(EvidenceReview).where(EvidenceReview.evidence_id.in_([f.id for f in files])).order_by(EvidenceReview.created_at.desc())).all()
        internal = policy.user(session).role != 'partner'
        requirement_rows = []
        for requirement in requirements:
            related = [f for f in files if f.requirement_id == requirement.id]
            status = 'approved' if any(f.review_status == 'approved' for f in related) else 'pending_review' if any(f.review_status == 'pending' for f in related) else 'missing'
            creator = session.get(User, requirement.created_by)
            requirement_rows.append({**requirement.model_dump(), 'status': status,
                                     'created_by_name': creator.display_name if creator else '已归档成员'})
        return {'files': [public_file(session, f) for f in files], 'requirements': requirement_rows,
                'reviews': [{**r.model_dump(), 'reviewer_name': session.get(User, r.reviewer_id).display_name} for r in reviews],
                'kinds': KINDS, 'max_file_bytes': storage.MAX_FILE_BYTES, 'max_order_files': storage.MAX_ORDER_FILES,
                'access': {'upload': True, 'review': internal, 'request': internal}}

    @app.post(prefix + '/evidence')
    def upload(order_id: str, data: Upload, request: Request, session: Session = Depends(signed_in)):
        policy.order_access(session, order_id)
        try:
            content = base64.b64decode(data.source_base64, validate=True)
            filename, media_type = storage.validate_content(data.filename, content)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error) if isinstance(error, ValueError) else '附件编码无效，请重新选择文件')
        digest = hashlib.sha256(content).hexdigest()
        signature = hashlib.sha256(json.dumps({'actor': policy.user(session).id, 'order': order_id, 'sha256': digest,
            'data': data.model_dump(exclude={'source_base64'})}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        # Serialize per-order submissions (including the file count) before checking replay.
        session.exec(update(TransportOrder).where(TransportOrder.id == order_id).values(version=TransportOrder.version))
        session.expire_all()
        auth.authenticate(session, request)
        policy.order_access(session, order_id)
        previous = session.exec(select(EvidenceFile).where(EvidenceFile.command_id == data.command_id)).first()
        if previous:
            if previous.signature != signature:
                raise HTTPException(409, '同一上传编号不能提交不同附件，请重新选择文件')
            return {**public_file(session, previous), 'replayed': True}
        check_unit(session, order_id, data.unit_id)
        if data.requirement_id:
            requirement = session.get(EvidenceRequirement, data.requirement_id)
            if not requirement or requirement.order_id != order_id or requirement.unit_id != data.unit_id or requirement.kind != data.kind:
                raise HTTPException(422, '请选择本票对应类型及单件范围的待补要求')
        count = len(session.exec(select(EvidenceFile.id).where(EvidenceFile.order_id == order_id)).all())
        if count >= storage.MAX_ORDER_FILES:
            raise HTTPException(422, '本票已达到30件附件上限，请先通过现有记录核对所需材料')
        record = EvidenceFile(id=identifier('EVD'), order_id=order_id, unit_id=data.unit_id, requirement_id=data.requirement_id,
            kind=data.kind, filename=filename, media_type=media_type, byte_size=len(content), sha256=digest,
            storage_key=storage.key(), uploaded_by=policy.user(session).id, uploaded_at=now(), note=data.note,
            command_id=data.command_id, signature=signature)
        path = None
        try:
            session.add(record)
            session.flush()
            path = storage.write_file(engine, record.storage_key, content)
            audit(session, order_id, 'evidence_uploaded', None,
                  {'evidence_id': record.id, 'kind': record.kind, 'filename': filename, 'sha256': digest, 'unit_id': data.unit_id})
            session.commit()
        except Exception as error:
            session.rollback()
            if path is not None and path.is_file():
                path.unlink()
            if isinstance(error, IntegrityError):
                raise HTTPException(409, '附件上传编号已使用，请刷新核对后重试')
            if isinstance(error, (OSError, ValueError)):
                raise HTTPException(422, '附件未保存成功，请检查本机存储空间后重试')
            raise
        return public_file(session, record)

    @app.get(prefix + '/evidence/{evidence_id}/download')
    def download(order_id: str, evidence_id: str, session: Session = Depends(signed_in)):
        record = file_access(session, order_id, evidence_id)
        try:
            content = storage.read_verified(engine, record)
        except (OSError, ValueError) as error:
            raise HTTPException(409, str(error) if isinstance(error, ValueError) else '附件文件暂时无法读取，请检查本机存储')
        return Response(content=content, media_type=record.media_type, headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(record.filename, safe=''),
            'Content-Security-Policy': "sandbox; default-src 'none'", 'X-Content-Type-Options': 'nosniff'})

    @app.post(prefix + '/evidence-requirements')
    def requirement(order_id: str, data: RequirementInput, session: Session = Depends(signed_in)):
        policy.internal_only(session)
        policy.order_access(session, order_id)
        check_unit(session, order_id, data.unit_id)
        def write():
            row = EvidenceRequirement(id=identifier('EVR'), order_id=order_id, kind=data.kind, unit_id=data.unit_id,
                note=data.note, created_by=policy.user(session).id, created_at=now())
            session.add(row)
            audit(session, order_id, 'evidence_requested', None, row.model_dump())
            return {'id': row.id}
        return business.command(session, policy.user(session).id + ':' + order_id + '/evidence-requirement', data, write)

    @app.post(prefix + '/evidence/{evidence_id}/reviews')
    def review(order_id: str, evidence_id: str, data: ReviewInput, session: Session = Depends(signed_in)):
        policy.internal_only(session)
        record = file_access(session, order_id, evidence_id)
        def write():
            if data.outcome == 'approved':
                try:
                    storage.read_verified(engine, record)
                except (OSError, ValueError):
                    raise HTTPException(409, '附件缺失或校验失败，不能确认复核通过，请恢复文件后再试')
            business.bump(session, record, data.version)
            record.review_status = data.outcome
            row = EvidenceReview(id=identifier('EVW'), evidence_id=evidence_id, reviewer_id=policy.user(session).id,
                outcome=data.outcome, note=data.note, created_at=now())
            session.add(record)
            session.add(row)
            audit(session, order_id, 'evidence_reviewed', None, row.model_dump())
            return {'id': row.id, 'evidence_id': evidence_id}
        return business.command(session, policy.user(session).id + ':' + evidence_id + '/review', data, write)
