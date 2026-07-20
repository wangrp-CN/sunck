// 通用附件 API（关联任意业务实体：作业计划/设备/人员/机械/...）
import { http } from "@/utils/request";
import type { Attachment } from "@/types";

// 上传文件并关联到实体，返回新建的 Attachment[]
export function uploadAttachments(
  entityType: string,
  entityId: number,
  files: File[],
): Promise<Attachment[]> {
  const form = new FormData();
  form.append("entity_type", entityType);
  form.append("entity_id", String(entityId));
  files.forEach((f) => form.append("files", f));
  return http<Attachment[]>({
    url: "/v1/attachments/upload",
    method: "POST",
    data: form,
    headers: { "Content-Type": "multipart/form-data" },
  });
}

// 列出某实体的全部有效附件
export function fetchAttachments(
  entityType: string,
  entityId: number,
): Promise<Attachment[]> {
  return http<Attachment[]>({
    url: "/v1/attachments",
    method: "GET",
    params: { entity_type: entityType, entity_id: entityId },
  });
}

// 删除附件（软删 + 删除 MinIO 对象）
export function deleteAttachment(id: number): Promise<void> {
  return http<void>({
    url: `/v1/attachments/${id}`,
    method: "DELETE",
  });
}
