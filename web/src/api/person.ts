import { http } from "@/utils/request";
import type { Person, PersonPage, PersonCreate, PersonUpdate } from "@/types";

// 人员分页列表
export function fetchPersons(params: {
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<PersonPage> {
  return http<PersonPage>({
    url: "/v1/persons",
    method: "GET",
    params,
  });
}

// 人员详情
export function fetchPerson(id: number): Promise<Person> {
  return http<Person>({
    url: `/v1/persons/${id}`,
    method: "GET",
  });
}

// 新建人员
export function createPerson(data: PersonCreate): Promise<Person> {
  return http<Person>({
    url: "/v1/persons",
    method: "POST",
    data,
  });
}

// 更新人员
export function updatePerson(id: number, data: PersonUpdate): Promise<Person> {
  return http<Person>({
    url: `/v1/persons/${id}`,
    method: "PUT",
    data,
  });
}

// 删除人员（软删）
export function deletePerson(id: number): Promise<null> {
  return http<null>({
    url: `/v1/persons/${id}`,
    method: "DELETE",
  });
}
