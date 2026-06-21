import Link from "next/link";
import { notFound } from "next/navigation";
import { updateCreator } from "@/app/actions";
import { Flash } from "@/components/flash";
import { createClient } from "@/lib/supabase/server";
import type { Creator } from "@/lib/types";

export default async function EditCreatorPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ error?: string }> }) {
  const { id } = await params;
  const { error } = await searchParams;
  const supabase = await createClient();
  const { data } = await supabase.from("creators").select("*").eq("id", id).single();
  if (!data) notFound();
  const creator = data as Creator;

  return <>
    <header className="topbar"><div><span className="eyebrow">Edit creator</span><h1 className="page-title">编辑 {creator.name}</h1><p className="page-subtitle">修改平台身份、分类和追踪状态。</p></div><Link className="button button-secondary" href={`/creators/${id}`}>取消</Link></header>
    <Flash error={error} />
    <section className="card"><form action={updateCreator.bind(null, id)} className="card-body">
      <div className="form-grid">
        <div className="field"><label className="required" htmlFor="name">名称</label><input className="input" id="name" name="name" defaultValue={creator.name} required /></div>
        <div className="field"><label className="required" htmlFor="platform">平台</label><select className="select" id="platform" name="platform" defaultValue={creator.platform}><option value="bilibili">B站</option><option value="douyin">抖音</option></select></div>
        <div className="field form-span-2"><label className="required" htmlFor="profile_url">主页链接</label><input className="input" id="profile_url" name="profile_url" type="url" defaultValue={creator.profile_url} required /></div>
        <div className="field"><label className="required" htmlFor="platform_creator_id">平台 ID</label><input className="input" id="platform_creator_id" name="platform_creator_id" defaultValue={creator.platform_creator_id} required /></div>
        <div className="field"><label htmlFor="sec_uid">抖音 SecUID</label><input className="input" id="sec_uid" name="sec_uid" defaultValue={creator.sec_uid ?? ""} /></div>
        <div className="field"><label htmlFor="category">分类</label><input className="input" id="category" name="category" defaultValue={creator.category ?? ""} /></div>
        <div className="field"><label>追踪状态</label><label className="checkbox-field"><input name="is_tracked" type="checkbox" defaultChecked={creator.is_tracked} /> 加入采集队列</label></div>
        <div className="field"><label htmlFor="follower_count">粉丝数</label><input className="input" id="follower_count" name="follower_count" type="number" min="0" defaultValue={creator.follower_count ?? ""} /></div>
        <div className="field"><label htmlFor="total_likes_count">抖音获赞数</label><input className="input" id="total_likes_count" name="total_likes_count" type="number" min="0" defaultValue={creator.total_likes_count ?? ""} /></div>
      </div>
      <div className="form-actions"><Link className="button button-secondary" href={`/creators/${id}`}>取消</Link><button className="button button-primary" type="submit">保存修改</button></div>
    </form></section>
  </>;
}

