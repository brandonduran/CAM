thres_cld = 0.001  
thres_cod = 0.3  
IF ( iovl = random OR iovl = maximum-random ) THEN
  clt(i) = 1.
ELSE
  clt(:) = 0
ENDIF  
icc(:) = 0  
lcc(:) = 0  
ttop(:) = 0  
cdr(:) = 0  
icr(:) = 0  
cdnc(:) = 0


DO i=1,nx
	DO k=2,nz ! assumption: uppermost layer is cloud-free (k=1)
		IF ( cod3d(i,k) > thres_cod and f3d(i,k) > thres_cld ) THEN ! visible, not-too-small cloud
			! flag_max is needed since the vertical integration for maximum overlap is different from the two others: for maximum, clt is the actual cloud cover in the level, for the two others, the actual cloud cover is 1 - clt
			! ftmp is total cloud cover seen from above down to the current level
			! clt is ftmp from the level just above
			! ftmp - clt is thus the additional cloud fraction seen from above in this level

			IF ( iovl = maximum ) THEN
				flag_max = -1.
				ftmp(i) = MAX( clt(i), f3d(i,k))  ! maximum overlap	
			ELSEIF ( iovl = random ) THEN
				flag_max = 1.
				ftmp(i) = clt(i) * ( 1 - f3d(i,k) ) ! random overlap	
			ELSEIF ( iovl = maximum-random ) THEN
				flag_max = 1.
				ftmp(i) = clt(i) * ( 1 - MAX( f3d(i,k), f3d(i,k-1) ) ) / &
   	            ( 1 - MIN( f3d(i,k-1), 1 - thres_cld ) )  ! maximum-random overlap	
			ENDIF
			ttop(i) = ttop(i) + t3d(i,k) * ( clt(i) - ftmp(i) )*flag_max 

			! ice clouds
			icr(i) = icr(i) + icr3d(i,k) * ( 1 - phase3d(i,k) ) * ( clt(i) - ftmp(i) )*flag_max 
			icc(i) = icc(i) + ( 1 - phase3d(i,k) ) * ( clt(i) - ftmp(i) )*flag_max 
	
			! liquid water clouds
			cdr(i) = cdr(i) + cdr3d(i,j) * phase3d(i,k) * ( clt(i) - ftmp(i) )*flag_max 
			cdnc(i) = cdnc(i) + cdnc3d(i,j) * phase3d(i,k) * ( clt(i) - ftmp(i) )*flag_max 
			lcc(i) = lcc(i) + phase3d(i,k) * ( clt(i) - ftmp(i) )*flag_max 
			
			clt(i) = ftmp(i)
		ENDIF ! is there a visible, not-too-small cloud?
	ENDDO ! loop over k

	IF ( iovl = random OR iovl = maximum-random ) THEN
		clt(i) = 1. - clt(i)
	ENDIF
ENDDO ! loop over I
