"""Reproducibly package untouched full-resolution NeuroMechFly STL surfaces.
Run with a NumPy-enabled Python; source bytes/ETags and reference FK are checked.
No decimation, procedural anatomy, or simulation is performed.
"""
from pathlib import Path
import concurrent.futures, hashlib, json, urllib.request, urllib.parse, xml.etree.ElementTree as ET
import numpy as np

HERE=Path(__file__).resolve().parent
FLYGYM_SHA='38c8ec61034cd59bc5ba0de20688d4a3c0000d60'
RIG_SHA='152506d3471646f009480c81f34aefbaec29a6e5'
PREFIX='flygym_assets/neuromechfly_fullsize_meshes_20260623a/'
S3='https://datasets.epfl.ch/nely-public-share/'

def fetch(url):
    return urllib.request.urlopen(url,timeout=60).read()

def build():
    cache=HERE/'source';cache.mkdir(exist_ok=True)
    rig_url=f'https://raw.githubusercontent.com/NeLy-EPFL/fly-svg-maker/{RIG_SHA}/assets/model.json'
    (HERE/'SOURCE-NOTICE.txt').write_bytes(fetch(f'https://raw.githubusercontent.com/NeLy-EPFL/fly-svg-maker/{RIG_SHA}/assets/NOTICE'))
    raw_rig=fetch(rig_url);(cache/'rig.json').write_bytes(raw_rig);rig=json.loads(raw_rig)
    license_url=f'https://raw.githubusercontent.com/NeLy-EPFL/flygym/{FLYGYM_SHA}/LICENSE'
    (HERE/'LICENSE-APACHE-2.0.txt').write_bytes(fetch(license_url))
    listing=ET.fromstring(fetch(S3+'?list-type=2&prefix='+urllib.parse.quote(PREFIX,safe='')))
    ns={'s':'http://s3.amazonaws.com/doc/2006-03-01/'}
    objects=[{'key':x.findtext('s:Key',namespaces=ns),'bytes':int(x.findtext('s:Size',namespaces=ns)),
              'etag':x.findtext('s:ETag',namespaces=ns).strip('"')} for x in listing.findall('s:Contents',ns)]
    assert sum(x['bytes'] for x in objects)<30_000_000
    def download(item):
        path=cache/Path(item['key']).name
        raw=path.read_bytes() if path.exists() else fetch(S3+item['key'])
        if len(raw)!=item['bytes'] or hashlib.md5(raw).hexdigest()!=item['etag']:raise ValueError('Source integrity mismatch: '+str(path))
        path.write_bytes(raw)
        return item|{'url':S3+item['key'],'sha256':hashlib.sha256(raw).hexdigest()}
    with concurrent.futures.ThreadPoolExecutor(6) as pool:sources=list(pool.map(download,objects))
    def quat(q):
        w,x,y,z=np.array(q)/np.linalg.norm(q)
        return np.array([[1-2*(y*y+z*z),2*(x*y-w*z),2*(x*z+w*y)],
          [2*(x*y+w*z),1-2*(x*x+z*z),2*(y*z-w*x)],[2*(x*z-w*y),2*(y*z+w*x),1-2*(x*x+y*y)]])
    def rotation(axis,theta):
        axis=np.asarray(axis,float);x,y,z=axis;c=np.cos(theta);s=np.sin(theta)
        return c*np.eye(3)+(1-c)*np.outer(axis,axis)+s*np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
    def rest(name):
        d=rig['rest'][name];m=np.eye(4);m[:3,:3]=quat(d['quat']);m[:3,3]=d['pos'];return m
    transforms={rig['root']:rest(rig['root'])}
    for parent,child in rig['joints']:
        r=np.eye(3)
        for dof in rig['dofs']:
            if dof['parent']==parent and dof['child']==child:
                axis=dof['axis'] if isinstance(dof['axis'],list) else rig['axisVector'][dof['axis']]
                r=r@rotation(axis,np.deg2rad(rig['neutralDeg'].get(dof['name'],0)))
        joint=np.eye(4);joint[:3,:3]=r;transforms[child]=transforms[parent]@rest(child)@joint
    error=max(float(np.abs(transforms[name][:3,3]-rig['reference']['neutralJointPositions'][name]).max()) for name in rig['segments'])
    assert error<1e-6,error
    chunks=[];offset=0;geometries={};vertices={}
    for name in sorted({x['file'] for x in rig['meshes'].values()}):
        raw=(cache/name).read_bytes();n=int.from_bytes(raw[80:84],'little');assert len(raw)==84+n*50
        dtype=np.dtype([('normal','<f4',3),('vertices','<f4',(3,3)),('attribute','<u2')])
        soup=np.frombuffer(raw,dtype=dtype,offset=84,count=n)['vertices'].astype(np.float64).reshape(-1,3)*rig['meshScale']
        v,inverse=np.unique(soup,axis=0,return_inverse=True);tri=inverse.reshape(-1,3)
        # Smooth vertex normals preserve all source triangles and coordinates.
        face=np.cross(v[tri[:,1]]-v[tri[:,0]],v[tri[:,2]]-v[tri[:,0]])
        normals=np.zeros_like(v)
        for j in range(3):np.add.at(normals,tri[:,j],face)
        length=np.linalg.norm(normals,axis=1);normals/=np.maximum(length[:,None],1e-30)
        arrays=[v.astype('<f4').ravel(),normals.astype('<f4').ravel(),tri.astype('<u4').ravel()]
        entry={'vertices':len(v),'triangles':n}
        for key,arr in zip(['positions','normals','indices'],arrays,strict=True):
            entry[key]={'byte_offset':offset,'count':len(arr)};b=arr.tobytes();chunks.append(b);offset+=len(b)
        geometries[name]=entry;vertices[name]=v
    binary=b''.join(chunks);(HERE/'full-resolution.bin').write_bytes(binary)
    segments=[];all_points=[]
    for name in rig['segments']:
        source=rig['meshes'][name];matrix=transforms[name].copy()
        if source['mirror']:matrix=matrix@np.diag([1,-1,1,1])
        v=vertices[source['file']]@matrix[:3,:3].T+matrix[:3,3]
        all_points.append(v)
        segments.append({'name':name,'geometry':source['file'],'matrix':matrix.T.ravel().tolist(),
                         'color':rig['colors'].get(name), 'bounds':[v.min(axis=0).tolist(),v.max(axis=0).tolist()]})
    cloud=np.concatenate(all_points);head=next(x for x in segments if x['name']=='c_head')
    out={'schema':1,'units':'mm','source_axes':'+X anterior, +Y left, +Z dorsal; official neutral pose',
      'source':'NeuroMechFly v2 full-resolution micro-CT-derived surfaces, EPFL',
      'license':'Apache-2.0','source_version':'neuromechfly_fullsize_meshes_20260623a','flygym_commit':FLYGYM_SHA,
      'rig_repository':'https://github.com/NeLy-EPFL/fly-svg-maker','rig_commit':RIG_SHA,
      'rig_sha256':hashlib.sha256(raw_rig).hexdigest(),'rig_url':rig_url,'sources':sources,
      'binary':'full-resolution.bin','binary_sha256':hashlib.sha256(binary).hexdigest(),
      'bytes':len(binary),'geometries':geometries,'segments':segments,
      'total_triangles':sum(geometries[s['geometry']]['triangles'] for s in segments),
      'bounds':[cloud.min(axis=0).tolist(),cloud.max(axis=0).tolist()],
      'head_bounds':head['bounds'],'neutral_pose_reference_max_error_mm':error,
      'processing':'Original triangles retained without decimation; identical positions indexed; area-weighted normals; right-side surfaces mirrored per official rig.',
      'brain_registration':'ASSUMPTION: different-fly FlyWire neurons fit inside head bounding box; orientation/scale approximate, not a co-registered anatomical atlas.'}
    (HERE/'manifest.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:out[k] for k in ['bytes','total_triangles','head_bounds','bounds','neutral_pose_reference_max_error_mm']}))
if __name__=='__main__':build()
