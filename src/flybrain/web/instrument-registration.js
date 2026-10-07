/** Registration is supplied explicitly; no transform is inferred from bounds. */
export function validateRegistration(document,{modelId,modelHash,volumeHash,dims}) {
  if(!document||document.schema_version!==1)throw new Error("Registration requires schema_version 1.");
  if(!modelId||!modelHash)throw new Error("The active anatomy needs a model ID and verified model hash before registration.");
  if(document.model_id!==modelId||document.model_hash!==modelHash)throw new Error("Registration belongs to a different model or model hash.");
  if(!volumeHash||document.volume_sha256!==volumeHash)throw new Error("Registration belongs to different NIfTI bytes.");
  if(!Array.isArray(document.volume_dims)||document.volume_dims.length!==3||document.volume_dims.some((n,i)=>n!==dims[i]))throw new Error("Registration volume dimensions do not match.");
  const m=document.model_um_to_voxel;
  if(!Array.isArray(m)||m.length!==4||m.some(row=>!Array.isArray(row)||row.length!==4||row.some(x=>typeof x!=="number"||!Number.isFinite(x))))throw new Error("Supply a finite 4 × 4 model_um_to_voxel matrix.");
  if(m[3].some((v,i)=>v!==[0,0,0,1][i]))throw new Error("Registration must be affine with last row [0, 0, 0, 1].");
  const det=m[0][0]*(m[1][1]*m[2][2]-m[1][2]*m[2][1])-m[0][1]*(m[1][0]*m[2][2]-m[1][2]*m[2][0])+m[0][2]*(m[1][0]*m[2][1]-m[1][1]*m[2][0]);
  if(!Number.isFinite(det)||det===0)throw new Error("Registration matrix is singular.");
  if(document.source_units!=="um"||document.target_units!=="voxel")throw new Error("Registration units must explicitly be source_units: um and target_units: voxel.");
  return {...document,model_um_to_voxel:m.map(row=>[...row]),volume_dims:[...document.volume_dims]};
}

export function registeredAnchors({positions,visibleIndices,centerUm,scaleUm,registration,dims,axis,slice}) {
  if(!positions||positions.length%3||!Array.isArray(centerUm)||centerUm.length!==3||!centerUm.every(Number.isFinite)||!Number.isFinite(scaleUm)||scaleUm<=0)throw new Error("Source anatomy is missing its normalized-coordinate transform.");
  const output=[],m=registration.model_um_to_voxel,indices=visibleIndices||Array.from({length:positions.length/3},(_,i)=>i);
  for(const index of indices){if(!Number.isInteger(index)||index<0||index*3+2>=positions.length)continue;const p=[0,1,2].map(i=>positions[index*3+i]*scaleUm+centerUm[i]),voxel=m.slice(0,3).map(row=>row[0]*p[0]+row[1]*p[1]+row[2]*p[2]+row[3]);if(voxel.every((v,i)=>Number.isFinite(v)&&v>=-.5&&v<dims[i]-.5)&&Math.abs(voxel[axis]-slice)<=.5)output.push({index,voxel});}
  return output;
}
