/** Importers preserve measured values; they never synthesize EEG or MRI from voltages. */
export function parseCsvRows(text) {
  const rows=[]; let row=[],cell="",quoted=false;
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(c==='"') {if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(!quoted&&cell.length)throw new Error("Unexpected quote in CSV cell.");else quoted=!quoted;}
    else if(c===","&&!quoted){row.push(cell);cell="";}
    else if((c==='\n'||c==='\r')&&!quoted){if(c==='\r'&&text[i+1]==='\n')i++;row.push(cell);if(row.some(v=>v.trim()))rows.push(row);row=[];cell="";}
    else cell+=c;
  }
  if(quoted)throw new Error("Unclosed quoted CSV cell.");
  row.push(cell);if(row.some(v=>v.trim()))rows.push(row);
  return rows;
}

export function parseEEGCsv(text,{timeUnit="auto",unit="as recorded"}={}) {
  const rows=parseCsvRows(text.replace(/^\uFEFF/,""));
  if(rows.length<3||rows[0].length<2)throw new Error("EEG CSV needs a time column, channel headers, and at least two samples.");
  const headers=rows.shift().map(v=>v.trim());
  if(headers.length>65)throw new Error("Import at most 64 channels per EEG panel.");
  if(timeUnit==="auto") {
    const first=headers[0].toLowerCase().replace(/\s/g,"");
    if(/(\[ms\]|\(ms\)|_ms|milliseconds)$/.test(first))timeUnit="ms";
    else if(/(\[s\]|\(s\)|_s|seconds)$/.test(first))timeUnit="s";
    else throw new Error("Choose seconds or milliseconds for the time column, or name it time_s / time_ms.");
  }
  if(!["s","ms"].includes(timeUnit))throw new Error("Choose seconds or milliseconds for EEG time.");
  const timeMs=new Float64Array(rows.length),channels=headers.slice(1).map((label,i)=>({label:label||`Channel ${i+1}`,unit,values:new Float64Array(rows.length)}));
  for(let i=0;i<rows.length;i++) {
    if(rows[i].length!==headers.length)throw new Error(`CSV row ${i+2} has a different number of columns.`);
    const values=rows[i].map(v=>v.trim()===""?NaN:Number(v));
    if(!values.every(Number.isFinite))throw new Error(`CSV row ${i+2} contains a missing or nonnumeric value.`);
    timeMs[i]=values[0]*(timeUnit==="s"?1000:1);
    if(i&&timeMs[i]<=timeMs[i-1])throw new Error("EEG sample times must be strictly increasing.");
    channels.forEach((channel,j)=>{channel.values[i]=values[j+1];});
  }
  return {timeMs,channels,timeUnit,unit,sampleCount:rows.length};
}

const NIFTI_TYPES={2:[1,"getUint8"],4:[2,"getInt16"],8:[4,"getInt32"],16:[4,"getFloat32"],64:[8,"getFloat64"],256:[1,"getInt8"],512:[2,"getUint16"],768:[4,"getUint32"]};

export function parseNifti(buffer) {
  if(!(buffer instanceof ArrayBuffer)||buffer.byteLength<352)throw new Error("NIfTI file is smaller than its header.");
  const view=new DataView(buffer),little=view.getInt32(0,true)===348;
  if(!little&&view.getInt32(0,false)!==348)throw new Error("Import a single-file NIfTI-1 .nii or .nii.gz volume.");
  if(String.fromCharCode(...new Uint8Array(buffer,344,4))!=="n+1\0")throw new Error("Only single-file NIfTI-1 (n+1) volumes are supported.");
  const ndim=view.getInt16(40,little);
  if(ndim<3||ndim>7)throw new Error("NIfTI needs three spatial dimensions and an optional time dimension.");
  const dims=Array.from({length:4},(_,i)=>i<ndim?view.getInt16(42+i*2,little):1);
  if(dims.some(n=>n<1))throw new Error("NIfTI dimensions must be positive.");
  for(let i=4;i<ndim;i++)if(view.getInt16(42+i*2,little)>1)throw new Error("Vector/tensor NIfTI dimensions are unsupported; import a scalar volume.");
  const type=view.getInt16(70,little),definition=NIFTI_TYPES[type];
  if(!definition||view.getInt16(72,little)!==definition[0]*8)throw new Error("Unsupported or inconsistent NIfTI scalar datatype.");
  const count=dims.reduce((a,b)=>a*b,1);
  if(!Number.isSafeInteger(count)||count>64_000_000)throw new Error("This viewer supports at most 64 million scalar voxels per imported volume.");
  const offset=view.getFloat32(108,little);
  if(!Number.isFinite(offset)||offset<352||offset%1||offset+count*definition[0]>buffer.byteLength)throw new Error("NIfTI voxel data are truncated or its offset is invalid.");
  const rawSlope=view.getFloat32(112,little),slope=rawSlope===0?1:rawSlope,intercept=rawSlope===0?0:view.getFloat32(116,little);
  if(!Number.isFinite(slope)||!Number.isFinite(intercept))throw new Error("NIfTI scaling parameters are nonfinite.");
  const spacing=Array.from({length:4},(_,i)=>Math.abs(view.getFloat32(80+i*4,little))||1);
  if(!spacing.every(Number.isFinite))throw new Error("NIfTI sample spacing is invalid.");
  const units=view.getUint8(123),timeScale={8:1000,16:1,24:0.001}[units&56];
  const timeStepMs=timeScale?spacing[3]*timeScale:null;
  const timeOffset=view.getFloat32(136,little),timeOriginMs=timeScale?timeOffset*timeScale:0;
  if(!Number.isFinite(timeOriginMs))throw new Error("NIfTI time offset is nonfinite.");
  const spatialUnit={1:"m",2:"mm",3:"µm"}[units&7]||"voxel units";
  const sformCode=view.getInt16(254,little),qformCode=view.getInt16(252,little);
  let affine=null;
  if(sformCode>0)affine=Array.from({length:3},(_,r)=>Array.from({length:4},(_,c)=>view.getFloat32(280+(r*4+c)*4,little)));
  else if(qformCode>0) {
    let b=view.getFloat32(256,little),c=view.getFloat32(260,little),d=view.getFloat32(264,little),a=1-(b*b+c*c+d*d);
    if(a<1e-7){const norm=Math.hypot(b,c,d);if(!norm)throw new Error("Invalid NIfTI quaternion.");b/=norm;c/=norm;d/=norm;a=0;}else a=Math.sqrt(a);
    const scale=[spacing[0],spacing[1],spacing[2]*(view.getFloat32(76,little)<0?-1:1)];
    const r=[[a*a+b*b-c*c-d*d,2*(b*c-a*d),2*(b*d+a*c)],[2*(b*c+a*d),a*a+c*c-b*b-d*d,2*(c*d-a*b)],[2*(b*d-a*c),2*(c*d+a*b),a*a+d*d-c*c-b*b]];
    affine=r.map((row,i)=>[...row.map((v,j)=>v*scale[j]),view.getFloat32(268+i*4,little)]);
  }
  if(affine&&!affine.flat().every(Number.isFinite))throw new Error("NIfTI affine contains nonfinite values.");
  const valueAt=(x,y,z,t=0)=>{
    if([x,y,z,t].some((v,i)=>!Number.isInteger(v)||v<0||v>=dims[i]))throw new Error("Voxel is outside the imported volume.");
    const index=x+dims[0]*(y+dims[1]*(z+dims[2]*t));
    return view[definition[1]](offset+index*definition[0],little)*slope+intercept;
  };
  const sample=[];const stride=Math.max(1,Math.ceil(count/100000));
  for(let i=0;i<count;i+=stride){const value=view[definition[1]](offset+i*definition[0],little)*slope+intercept;if(Number.isFinite(value))sample.push(value);}
  sample.sort((a,b)=>a-b);
  if(!sample.length)throw new Error("The imported volume has no finite voxels.");
  let low=sample[Math.floor((sample.length-1)*.02)],high=sample[Math.floor((sample.length-1)*.98)];if(high===low)high=low+1;
  return {dims,spacing,timeStepMs,timeOriginMs,spatialUnit,affine,valueAt,low,high,datatype:type,
    voxelToWorld:(x,y,z)=>affine?affine.map(row=>row[0]*x+row[1]*y+row[2]*z+row[3]):null};
}

export async function readNiftiFile(file) {
  if(file.size>256*1024*1024)throw new Error("Choose a volume file smaller than 256 MiB.");
  let buffer=await file.arrayBuffer();
  if(new Uint8Array(buffer)[0]===0x1f&&new Uint8Array(buffer)[1]===0x8b) {
    if(typeof DecompressionStream==="undefined")throw new Error("This browser cannot decompress .nii.gz. Unzip the file and import its .nii file.");
    const reader=new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip")).getReader();
    const chunks=[];let size=0;
    while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>512*1024*1024){await reader.cancel();throw new Error("Decompressed NIfTI exceeds 512 MiB.");}chunks.push(value);}
    const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.length;}buffer=bytes.buffer;
  }
  const parsed=parseNifti(buffer);
  parsed.sha256=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",buffer)),v=>v.toString(16).padStart(2,"0")).join("");
  return parsed;
}

/** Snapshot a voxel on the file's declared clock, including its nonzero origin. */
export function niftiVoxelSeries(volume,selection) {
  const count=volume?.dims?.[3],step=volume?.timeStepMs,origin=volume?.timeOriginMs??0;
  if(!Number.isInteger(count)||count<2||!Number.isFinite(step)||step<=0||!Number.isFinite(origin))throw new Error('This volume needs at least two frames and declared finite time units to chart a voxel.');
  if(!Array.isArray(selection)||selection.length!==3)throw new Error('Select one voxel in the imported volume.');
  return{timeMs:Float64Array.from({length:count},(_,i)=>origin+i*step),values:Float64Array.from({length:count},(_,i)=>volume.valueAt(...selection,i))};
}
